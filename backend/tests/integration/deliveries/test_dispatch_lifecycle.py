"""A slip's whole life: raised, dispatched, confirmed (spec §10).

The thing being tested throughout is the **join**. A dispatch is one action that has to land in
four places at once - the slip, the order, the stock ledger and the bell - and the failures worth
catching are all partial: stock gone with no delivery behind it, a customer told their cylinders
are coming while they sit in the godown, an order stuck out for delivery for a van that never
loaded. So most of these assert all four sides of one call.
"""

import pytest
from sqlalchemy import select

from app.modules.inventory.models import StockMovement
from app.modules.orders.models import Order, OrderStatusHistory
from app.shared.notifications.models import NotificationOutbox
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    counts,
    dispatch_staff,
    make_customer,
    place_order,
    price_cylinders,
    ready_to_dispatch,
    refill,
    slip_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def notifications_for(env, recipient_id: str) -> list[tuple[str, str]]:
    """(event_type, title) of everything queued for one recipient."""
    rows = list(
        await env.execute(
            select(NotificationOutbox.event_type, NotificationOutbox.title).where(
                NotificationOutbox.recipient_id == recipient_id
            )
        )
    )
    return [(row.event_type, row.title) for row in rows]


async def order_status(env, order_id: str) -> str:
    return await env.scalar(select(Order.status).where(Order.id == order_id))


async def history_of(env, order_id: str) -> list[tuple[str, str | None]]:
    rows = list(
        await env.execute(
            select(OrderStatusHistory.status, OrderStatusHistory.note)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id)
        )
    )
    return [(row.status, row.note) for row in rows]


# --- Raising a slip ---------------------------------------------------------------------------


async def test_a_slip_copies_the_order_onto_itself(env):
    """A slip is a copy, not a live view: it has to keep saying what went on the van."""
    _token, _merchant, order, slip, _driver = await ready_to_dispatch(env)

    assert slip["orderId"] == order["id"]
    assert slip["orderNumber"] == order["orderNumber"]
    assert slip["customerName"] == "Sharma General Store"
    assert slip["itemsSummary"] == order["itemsSummary"]
    assert slip["cylindersAllocated"] == order["totalCylinders"]
    assert [(item["cylinderType"], item["quantity"]) for item in slip["items"]] == [("LPG_19KG", 4)]
    assert slip["deliveryAddress"]["line1"] == "Shop 14, Sapna Sangeeta Road"
    assert slip["deliveryAddress"]["pincode"] == "452001"


async def test_a_new_slip_is_scheduled_and_carries_no_stock_yet(env):
    """Raising a slip is the loading instruction, not the loading."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    assert slip["status"] == "SCHEDULED"
    assert slip["dispatchedAt"] is None
    assert slip["deliveredAt"] is None
    assert slip["emptiesCollected"] == 0
    assert slip["pendingPickup"] == 4
    assert await counts(env, token) == (60, 0, 0), "nothing moved off the shelf"


async def test_slip_numbers_run_per_merchant(env):
    """`DS-0001`, `DS-0002`. Staff read these out and file the paper copy by them."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, quantity=60)
    numbers = []
    for _ in range(3):
        order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
        created = await env.post(
            DELIVERIES, token, {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"}
        )
        assert created.status_code == 201, created.text
        numbers.append(created.json()["slipNumber"])

    assert numbers == ["DS-0001", "DS-0002", "DS-0003"]


async def test_the_order_points_back_at_its_slip(env):
    """Which is what the order detail screen and invoicing both read."""
    _token, _merchant, order, slip, _driver = await ready_to_dispatch(env)

    linked = await env.scalar(select(Order.delivery_slip_id).where(Order.id == order["id"]))

    assert linked == slip["id"]


async def test_the_assigned_driver_is_told(env):
    """The delivery app's bell. This is why the slip carries a driver *user*, not just a name."""
    _token, _merchant, _order, _slip, driver = await ready_to_dispatch(env)

    assert ("DELIVERY_ASSIGNED", "New delivery assigned") in await notifications_for(env, driver.id)


async def test_a_hired_van_needs_no_account(env):
    """A merchant running a hired van must still be able to raise the slip."""
    token, _merchant, _order, slip, driver = await ready_to_dispatch(env, with_driver=False)

    assert driver is None
    assert slip["driverName"] == "Hired van driver"
    assert slip["status"] == "SCHEDULED"
    assert (await env.get(f"{DELIVERIES}/{slip['id']}", token)).status_code == 200


# --- Dispatch ----------------------------------------------------------------------------------


async def test_dispatch_lands_in_all_four_places_at_once(env):
    """The slip, the order, the ledger and the bell - one call, one transaction."""
    token, _merchant, order, slip, _driver = await ready_to_dispatch(env)

    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert response.status_code == 200, response.text
    dispatched = response.json()
    # 1. the slip
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatchedAt"] is not None
    # 2. the order
    assert await order_status(env, order["id"]) == "OUT_FOR_DELIVERY"
    # 3. the ledger
    assert await counts(env, token) == (56, 0, 0)
    # 4. the customer
    titles = [title for _event, title in await notifications_for(env, order["customerId"])]
    assert "Order out for delivery" in titles


async def test_the_order_history_names_the_van_and_the_driver(env):
    """Spec §10.3 fixes this wording: it is what a customer ringing up is read back."""
    token, _merchant, order, slip, _driver = await ready_to_dispatch(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    trail = await history_of(env, order["id"])
    assert ("OUT_FOR_DELIVERY", "Vehicle MP09 GH 4521 · Test Driver") in trail


async def test_the_dispatch_movement_points_at_the_slip(env):
    """`referenceType: DELIVERY` - which is how a slip is reconciled back to the counts."""
    token, merchant, _order, slip, _driver = await ready_to_dispatch(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    row = await env.scalar(
        select(StockMovement).where(
            StockMovement.merchant_id == merchant.id,
            StockMovement.movement_type == "DISPATCHED",
        )
    )
    assert row.reference_type == "DELIVERY"
    assert row.reference_id == slip["id"]
    assert (row.delta_filled, row.quantity) == (-4, 4)


async def test_a_dispatch_short_on_stock_changes_nothing_anywhere(env):
    """Spec §10.3: "no counts change" - and nor does anything else.

    This is the test that matters most in the module. A partial dispatch means cylinders left the
    books without leaving the godown, and a customer told their order is on the way.
    """
    token, _merchant, order, slip, _driver = await ready_to_dispatch(env, quantity=2)

    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == (
        "Not enough filled 19 KG in stock (2 available, 4 needed). Record a refill first."
    )
    assert (await slip_of(env, token, slip["id"]))["status"] == "SCHEDULED"
    # Still CONFIRMED: raising a slip is planning, and a refused dispatch means nothing
    # physically happened.
    assert await order_status(env, order["id"]) == "CONFIRMED"
    assert await counts(env, token) == (2, 0, 0)
    titles = [title for _event, title in await notifications_for(env, order["customerId"])]
    assert "Order out for delivery" not in titles


async def test_a_refill_then_a_retry_dispatches(env):
    """The refusal is recoverable, which is what makes "record a refill first" honest advice."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env, quantity=2)
    assert (await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)).status_code == 409

    await refill(env, token, quantity=10)
    retried = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert retried.status_code == 200
    assert await counts(env, token) == (8, 0, 0)


async def test_a_slip_cannot_be_dispatched_twice(env):
    """Otherwise the second call takes the cylinders off the shelf a second time."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    again = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert again.status_code == 409
    assert "already been dispatched" in again.json()["detail"]["message"]
    assert await counts(env, token) == (56, 0, 0), "the stock moved once"


# --- Confirmation ------------------------------------------------------------------------------


async def dispatched(env, *, quantity: int = 60, lines=()):
    """A slip already on the road, plus its confirmation code."""
    token, merchant, order, slip, driver = await ready_to_dispatch(env, *lines, quantity=quantity)
    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)
    assert response.status_code == 200, response.text
    dispatched_slip = response.json()
    # Minted by the dispatch, which is also what tells the customer.
    return token, merchant, order, dispatched_slip, driver, dispatched_slip["devConfirmationCode"]


async def test_confirming_completes_the_delivery(env):
    token, _merchant, order, slip, _driver, code = await dispatched(env)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm",
        token,
        {"otp": code, "emptiesCollected": 3, "note": "Left 1 empty for next visit"},
    )

    assert response.status_code == 200, response.text
    confirmed = response.json()
    assert confirmed["status"] == "DELIVERED"
    assert confirmed["deliveredAt"] is not None
    assert confirmed["emptiesCollected"] == 3
    assert confirmed["pendingPickup"] == 1
    assert confirmed["note"] == "Left 1 empty for next visit"
    assert await order_status(env, order["id"]) == "DELIVERED"
    titles = [title for _event, title in await notifications_for(env, order["customerId"])]
    assert "Order delivered" in titles


async def test_collected_empties_go_back_into_stock(env):
    """`deltas.empty = +n` (spec §10.4). The empty bucket is what BPCL gets back."""
    token, _merchant, _order, slip, _driver, code = await dispatched(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 4})

    assert await counts(env, token) == (56, 4, 0)


async def test_no_empties_collected_is_a_valid_delivery(env):
    """A first-time customer has nothing to give back, and the slip still completes."""
    token, _merchant, _order, slip, _driver, code = await dispatched(env)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 0}
    )

    assert response.status_code == 200
    assert response.json()["pendingPickup"] == 4
    assert await counts(env, token) == (56, 0, 0), "no empties, so no movement"


async def test_a_wrong_code_refuses_the_confirmation(env):
    token, _merchant, order, slip, _driver, _code = await dispatched(env)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "0000", "emptiesCollected": 0}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0] == {
        "field": "otp",
        "code": "incorrect_otp",
        "message": "Incorrect OTP",
    }
    assert (await slip_of(env, token, slip["id"]))["status"] == "DISPATCHED"
    assert await order_status(env, order["id"]) == "OUT_FOR_DELIVERY"


async def test_more_empties_than_cylinders_is_refused(env):
    """Otherwise the driver books somebody else's cylinders onto this slip."""
    token, _merchant, _order, slip, _driver, code = await dispatched(env)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 5}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["message"] == "Invalid count"
    assert await counts(env, token) == (56, 0, 0)


async def test_a_slip_cannot_be_confirmed_before_it_is_dispatched(env):
    """Spec §10.4 asks for this message specifically."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    # A scheduled slip has no code yet, so the mock one stands in - the point of the test is the
    # state check, which has to run before the code is even looked at.
    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "4321", "emptiesCollected": 0}
    )

    assert response.status_code == 409
    assert "has not been dispatched yet" in response.json()["detail"]["message"]


async def test_a_slip_cannot_be_confirmed_twice(env):
    token, _merchant, _order, slip, _driver, code = await dispatched(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 2})

    again = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 2}
    )

    assert again.status_code == 409
    assert "already been delivered" in again.json()["detail"]["message"]
    assert await counts(env, token) == (56, 2, 0), "the empties were booked once"


async def test_the_code_is_spent_once_the_slip_is_confirmed(env):
    """A code that still verifies against a settled slip is a secret with no purpose."""
    token, merchant, _order, slip, _driver, _code = await dispatched(env)
    from app.modules.deliveries.models import DeliverySlip

    await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": _code, "emptiesCollected": 0})

    stored = await env.scalar(
        select(DeliverySlip.confirmation_code_hash).where(DeliverySlip.id == slip["id"])
    )
    assert stored is None
    assert merchant


# --- The whole cycle reconciles ------------------------------------------------------------------


async def test_the_full_cycle_leaves_the_ledger_agreeing_with_the_counts(env):
    """Sixty in, four out on a van, four empties back - and §18.6 still holds."""
    token, merchant, order, slip, _driver, code = await dispatched(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 4})

    filled, empty, damaged = await counts(env, token)
    rows = list(
        await env.execute(
            select(
                StockMovement.delta_filled, StockMovement.delta_empty, StockMovement.delta_damaged
            ).where(StockMovement.merchant_id == merchant.id)
        )
    )
    assert (filled, empty, damaged) == (56, 4, 0)
    assert sum(row.delta_filled for row in rows) == filled
    assert sum(row.delta_empty for row in rows) == empty
    assert await order_status(env, order["id"]) == "DELIVERED"


async def test_a_multi_line_slip_dispatches_every_line(env):
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(
        env, ("LPG_19KG", 4), ("LPG_5KG", 6)
    )

    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert response.status_code == 200, response.text
    assert await counts(env, token, "LPG_19KG") == (56, 0, 0)
    assert await counts(env, token, "LPG_5KG") == (54, 0, 0)
    assert response.json()["cylindersAllocated"] == 10
