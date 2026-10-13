"""Whether the Cancel button should be on the screen at all.

The rule has always been right in the backend - an order may be cancelled while it is `PLACED`
or `CONFIRMED` and not after, because past that the cylinders are on a van and the customer is
holding the code. What was missing is that it was never *said*. Nothing on the order told an
app whether cancelling would work, so the merchant app and the customer app each kept their own
guess, and both offered Cancel on a delivery whose driver was standing at the gate. The press
came back a 409 and the person reading it had no idea why.

`canCancel` is that rule, read off the same helper the endpoint refuses with, so the button and
the refusal can never disagree.

**The answer differs by who is asking**, which is the other reason the apps must read it rather
than infer it: the office can call off a round that is already out - they can reach the driver,
and no stock has moved because counts only drop at handover - while the customer's own app
stops at the godown door.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip
from app.shared.notifications.models import NotificationOutbox

from tests.integration.driver.conftest import DRIVER_DELIVERIES, driver_token
from tests.integration.orders.conftest import CUSTOMER_ORDERS, customer_token
from tests.integration.deliveries.conftest import (
    ORDERS,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    refill,
    settings_overrides,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

VAN = "MP09 GH 4521"


async def an_order(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 40)
    driver = await make_driver(env, merchant)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    return token, order, driver


async def customer_of(env, order) -> object:
    """The profile behind an order, for signing in as them."""
    from app.modules.customers.models import CustomerProfile

    async with env.sessions() as db:
        return await db.scalar(
            select(CustomerProfile).where(CustomerProfile.id == order["customerId"])
        )


async def order_body(env, token, order_id) -> dict:
    response = await env.get(f"{ORDERS}/{order_id}", token)
    assert response.status_code == 200, response.text
    return response.json()


async def send_the_van_out(env, slip_id, driver) -> None:
    """Dispatch is the driver's own action; the office has no endpoint for it."""
    drivers = await driver_token(env, driver)
    out = await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers, {})
    assert out.status_code == 200, out.text


async def confirm(env, token, order, driver) -> str:
    response = await env.post(
        f"{ORDERS}/{order['id']}/confirm",
        token,
        {"delivery": {"vehicleNumber": VAN, "driverUserId": driver.id}},
    )
    assert response.status_code == 200, response.text
    return response.json()["deliverySlipId"]


# --- What the flag says ------------------------------------------------------------------------


async def test_a_placed_order_may_still_be_cancelled(env):
    token, order, _driver = await an_order(env)

    assert (await order_body(env, token, order["id"]))["canCancel"] is True


async def test_a_confirmed_order_may_still_be_cancelled(env):
    """The van has not left: the office can still change its mind."""
    token, order, driver = await an_order(env)
    await confirm(env, token, order, driver)

    assert (await order_body(env, token, order["id"]))["canCancel"] is True


async def test_the_office_may_still_cancel_an_order_on_the_van(env):
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)

    await send_the_van_out(env, slip_id, driver)

    assert (await order_body(env, token, order["id"]))["canCancel"] is True


async def test_cancelling_a_round_that_is_out_closes_its_slip(env):
    """Otherwise the driver keeps a delivery he cannot complete and nobody can take off him."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)

    cancelled = await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    assert cancelled.status_code == 200, cancelled.text
    async with env.sessions() as db:
        slip = await db.scalar(select(DeliverySlip).where(DeliverySlip.id == slip_id))
    assert slip.status == "FAILED"


async def test_a_cancelled_order_may_not_be_cancelled_again(env):
    token, order, _driver = await an_order(env)
    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Customer changed mind"})

    assert (await order_body(env, token, order["id"]))["canCancel"] is False


# --- The flag and the endpoint cannot disagree ---------------------------------------------------


async def test_the_button_and_the_refusal_agree(env):
    """`canCancel` false and the endpoint accepting it would be the worse of the two bugs."""
    token, order, _driver = await an_order(env)
    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Not needed"})
    assert (await order_body(env, token, order["id"]))["canCancel"] is False

    again = await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Again"})

    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "ORDER_NOT_CANCELLABLE"


async def test_the_flag_is_true_exactly_when_cancelling_works(env):
    token, order, _driver = await an_order(env)
    assert (await order_body(env, token, order["id"]))["canCancel"] is True

    response = await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Not needed"})

    assert response.status_code == 200, response.text


async def test_the_flag_is_on_the_order_list_too(env):
    """The list is where the button is drawn, so it has to carry the answer."""
    token, order, _driver = await an_order(env)

    listed = await env.get(ORDERS, token)

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    row = next(r for r in (rows["items"] if isinstance(rows, dict) else rows) if r["id"] == order["id"])
    assert row["canCancel"] is True


# --- The customer's own app is stricter -----------------------------------------------------------


async def test_the_customer_may_not_cancel_a_round_that_is_out(env):
    """The office can ring the driver; the customer standing in front of the van cannot call the
    delivery off from their phone. Same order, same moment, different answer."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)
    theirs = await customer_token(env, await customer_of(env, order))

    response = await env.post(f"{CUSTOMER_ORDERS}/{order['id']}/cancel", theirs, {"reason": "No"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ORDER_NOT_CANCELLABLE"


async def test_the_customer_sees_the_button_hidden_at_that_moment(env):
    """And `canCancel` says so, so the app never offers a press that would be refused."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)
    theirs = await customer_token(env, await customer_of(env, order))

    mine = await env.get(f"{CUSTOMER_ORDERS}/{order['id']}", theirs)

    assert mine.status_code == 200, mine.text
    assert mine.json()["canCancel"] is False


async def test_the_customer_may_still_cancel_before_the_van_leaves(env):
    token, order, driver = await an_order(env)
    await confirm(env, token, order, driver)
    theirs = await customer_token(env, await customer_of(env, order))

    response = await env.post(
        f"{CUSTOMER_ORDERS}/{order['id']}/cancel", theirs, {"reason": "Changed my mind"}
    )

    assert response.status_code == 200, response.text


# --- The code the office can now read -------------------------------------------------------------


async def test_the_office_can_read_the_delivery_code(env):
    """A staff-placed order never reaches the customer's phone, so the driver at the gate has
    to be able to ring somebody who can see it."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)

    body = await order_body(env, token, order["id"])

    assert body["deliveryOtp"]
    assert len(body["deliveryOtp"]) == 4


async def test_another_merchants_code_is_not_readable(env):
    """Their delivery, their code. The office sees its own agency's and no further."""
    token, _order, _driver = await an_order(env)
    other_token, theirs, their_driver = await an_order(env)
    their_slip = await confirm(env, other_token, theirs, their_driver)
    await send_the_van_out(env, their_slip, their_driver)

    response = await env.get(f"{ORDERS}/{theirs['id']}", token)

    assert response.status_code == 404, response.text


async def test_the_code_is_spent_once_the_handover_is_confirmed(env):
    """Neither side keeps a code that would still verify against a settled slip."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)
    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    assert (await order_body(env, token, order["id"]))["deliveryOtp"] is None


# --- The driver has to be told ---------------------------------------------------------------------


async def notices_for(env, user_id: str) -> list[NotificationOutbox]:
    async with env.sessions() as db:
        return list(
            await db.scalars(
                select(NotificationOutbox).where(NotificationOutbox.recipient_id == user_id)
            )
        )


async def test_a_driver_on_the_road_is_told_to_stop(env):
    """The office can call off a round that is already out, so by the time it is cancelled the
    van may be at the gate. A driver who is not interrupted hands over cylinders against an
    order that no longer exists."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)

    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    events = {n.event_type for n in await notices_for(env, driver.id)}
    assert "DELIVERY_ORDER_CANCELLED" in events


async def test_that_warning_is_critical(env):
    """It is the one delivery notification that has to interrupt whatever he is doing."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)

    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    notice = next(
        n for n in await notices_for(env, driver.id) if n.event_type == "DELIVERY_ORDER_CANCELLED"
    )
    assert notice.severity == "CRITICAL"


async def test_a_round_still_at_the_godown_is_an_ordinary_unassignment(env):
    """Nothing to interrupt - the van has not left, the round simply loses a stop."""
    token, order, driver = await an_order(env)
    await confirm(env, token, order, driver)

    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Customer changed mind"})

    events = {n.event_type for n in await notices_for(env, driver.id)}
    assert "DELIVERY_UNASSIGNED" in events
    assert "DELIVERY_ORDER_CANCELLED" not in events


async def test_the_customer_is_told_as_well(env):
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)

    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    customer = await customer_of(env, order)
    assert await notices_for(env, customer.id), "the customer was not notified"


async def test_the_cancelled_round_reads_as_failed_on_the_drivers_list(env):
    """The notification is only half of it - his list has to agree with it.

    The stop stays, because a round that emptied as he worked would not tell him how far
    through the day he is. What changes is its `status`, so the app can strike it out beside
    the warning that it was cancelled.
    """
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)
    drivers = await driver_token(env, driver)
    before = await env.get(f"{DRIVER_DELIVERIES}/today", drivers)
    assert next(r for r in before.json() if r["id"] == slip_id)["status"].upper() != "FAILED"

    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    after = await env.get(f"{DRIVER_DELIVERIES}/today", drivers)
    assert next(r for r in after.json() if r["id"] == slip_id)["status"].upper() == "FAILED"


async def test_he_cannot_complete_it_afterwards(env):
    """Whatever the screen shows, the handover has to be refused."""
    token, order, driver = await an_order(env)
    slip_id = await confirm(env, token, order, driver)
    await send_the_van_out(env, slip_id, driver)
    drivers = await driver_token(env, driver)
    await env.post(f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Recalled"})

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": 2}],
         "collectedEmpties": [], "payment": None, "driverNotes": None},
    )

    assert response.status_code == 409, response.text
