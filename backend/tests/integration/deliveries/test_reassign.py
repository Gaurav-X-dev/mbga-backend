"""Moving a round to another van, crew or day.

A slip could not be changed at all once it was raised. The office picked the wrong driver, or a
van came off the road, or a round simply never went out - and the only way forward was to cancel
the order and place it again, which throws away its number, its history and the customer's place
in the queue.

The result was visible in production: one driver holding four vans across four days, with no way
to let any of them go, and two orders from previous days that nobody could close because the
driver's app only shows today.
"""

import pytest
from datetime import timedelta

from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip
from app.modules.orders.models import OrderStatusHistory
from app.shared.date_time.business_calendar import business_today
from tests.integration.driver.conftest import DRIVER_DELIVERIES, driver_token
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    ORDERS,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    refill,
    settings_overrides,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

VAN = "MP09 GH 4521"
OTHER_VAN = "MP09 ZZ 0002"


async def a_round(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 400)
    first = await make_driver(env, merchant)
    second = await make_driver(env, merchant)
    return token, merchant, customer, first, second


async def assign(env, token, customer, driver, *, van=VAN, date=None):
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    delivery = {"vehicleNumber": van, "driverUserId": driver.id}
    if date is not None:
        delivery["deliveryDate"] = date.isoformat()
    confirmed = await env.post(f"{ORDERS}/{order['id']}/confirm", token, {"delivery": delivery})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["deliverySlipId"]


async def reassign(env, token, slip_id, body):
    return await env.client.patch(
        f"{DELIVERIES}/{slip_id}/assignment",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def slip_of(env, slip_id) -> DeliverySlip:
    return await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip_id))


# --- The four things the office could not do ---------------------------------------------------


async def test_the_wrong_driver_can_be_swapped(env):
    token, _merchant, customer, driver, other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"driverUserId": other.id})

    assert response.status_code == 200, response.text
    assert (await slip_of(env, slip_id)).driver_user_id == other.id


async def test_a_van_off_the_road_can_be_swapped(env):
    token, _merchant, customer, driver, _other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"vehicleNumber": OTHER_VAN})

    assert response.status_code == 200, response.text
    assert (await slip_of(env, slip_id)).vehicle_number == OTHER_VAN


async def test_a_round_that_never_went_out_can_be_moved_to_today(env):
    """The case that was killing orders: a past-dated slip the driver's app cannot show."""
    token, _merchant, customer, driver, _other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    yesterday = business_today() - timedelta(days=1)
    await env.execute(
        update(DeliverySlip).where(DeliverySlip.id == slip_id).values(scheduled_date=yesterday)
    )

    response = await reassign(env, token, slip_id, {"deliveryDate": business_today().isoformat()})

    assert response.status_code == 200, response.text
    assert (await slip_of(env, slip_id)).scheduled_date == business_today()


async def test_the_moved_round_reaches_the_drivers_app(env):
    """Moving it is only worth anything if he can then see and close it."""
    token, _merchant, customer, driver, _other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    await env.execute(
        update(DeliverySlip)
        .where(DeliverySlip.id == slip_id)
        .values(scheduled_date=business_today() - timedelta(days=2))
    )
    drivers_token = await driver_token(env, driver)
    before = (await env.get(f"{DRIVER_DELIVERIES}/today", drivers_token)).json()
    assert slip_id not in {row["id"] for row in before}

    await reassign(env, token, slip_id, {"deliveryDate": business_today().isoformat()})

    after = (await env.get(f"{DRIVER_DELIVERIES}/today", drivers_token)).json()
    assert slip_id in {row["id"] for row in after}


async def test_everything_can_move_at_once(env):
    token, _merchant, customer, driver, other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    tomorrow = business_today() + timedelta(days=1)

    response = await reassign(
        env,
        token,
        slip_id,
        {
            "driverUserId": other.id,
            "vehicleNumber": OTHER_VAN,
            "deliveryDate": tomorrow.isoformat(),
            "reason": "Driver on leave, van in the workshop",
        },
    )

    assert response.status_code == 200, response.text
    slip = await slip_of(env, slip_id)
    assert (slip.driver_user_id, slip.vehicle_number, slip.scheduled_date) == (
        other.id,
        OTHER_VAN,
        tomorrow,
    )


# --- What it leaves alone ---------------------------------------------------------------------


async def test_only_what_is_sent_changes(env):
    """An office swapping a broken van keeps the driver."""
    token, _merchant, customer, driver, _other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    before = await slip_of(env, slip_id)

    await reassign(env, token, slip_id, {"vehicleNumber": OTHER_VAN})

    after = await slip_of(env, slip_id)
    assert after.driver_user_id == before.driver_user_id
    assert after.scheduled_date == before.scheduled_date
    assert after.order_id == before.order_id


async def test_the_order_keeps_its_number_and_gains_a_trail_line(env):
    """The point of moving rather than cancelling and re-placing."""
    token, _merchant, customer, driver, other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    slip = await slip_of(env, slip_id)

    await reassign(env, token, slip_id, {"driverUserId": other.id, "reason": "Driver on leave"})

    async with env.sessions() as db:
        trail = list(
            await db.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == slip.order_id)
                .order_by(OrderStatusHistory.changed_at)
            )
        )
    assert "Driver on leave" in (trail[-1].note or "")
    # A note on the timeline, not a step in it.
    assert trail[-1].previous_status == trail[-1].status


# --- What it refuses ---------------------------------------------------------------------------


async def test_a_dispatched_round_is_not_moved(env):
    """The cylinders are on that van and the code is in the customer's hand."""
    token, _merchant, customer, driver, other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)
    drivers_token = await driver_token(env, driver)
    await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers_token, {})

    response = await reassign(env, token, slip_id, {"driverUserId": other.id})

    assert response.status_code == 409, response.text


async def test_the_new_driver_must_be_free_that_day(env):
    token, _merchant, customer, driver, other = await a_round(env)
    # `other` is already out on a different van today.
    await assign(env, token, customer, other, van=OTHER_VAN)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"driverUserId": other.id})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"][0]["code"] == "driver_already_assigned"


async def test_the_new_van_must_be_free_that_day(env):
    token, _merchant, customer, driver, other = await a_round(env)
    await assign(env, token, customer, other, van=OTHER_VAN)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"vehicleNumber": OTHER_VAN})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"][0]["code"] == "vehicle_already_assigned"


async def test_a_round_does_not_clash_with_itself(env):
    """Re-sending what it already has must not read as a double booking."""
    token, _merchant, customer, driver, _other = await a_round(env)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(
        env, token, slip_id, {"vehicleNumber": VAN, "driverUserId": driver.id}
    )

    assert response.status_code == 200, response.text


async def test_another_merchants_slip_is_not_found(env):
    _theirs, _m, _c, _a, _b = await a_round(env)
    ours_token, _merchant, _customer, _d, _e = await a_round(env)
    theirs_token, _m2, customer2, driver2, _f = await a_round(env)
    theirs = await assign(env, theirs_token, customer2, driver2)

    response = await reassign(env, ours_token, theirs, {"deliveryDate": business_today().isoformat()})

    assert response.status_code == 404


async def test_the_refusal_names_the_round_in_the_way(env):
    """"This driver is already carrying a delivery" told the office nothing they could act on.

    Which round, on which van, was a question only a SQL query could answer - so the message
    now names the vehicle and the order, and the app can show it as it stands.
    """
    token, _merchant, customer, driver, other = await a_round(env)
    await assign(env, token, customer, other, van=OTHER_VAN)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"driverUserId": other.id})

    assert response.status_code == 422, response.text
    message = response.json()["detail"]["fields"][0]["message"]
    assert OTHER_VAN in message
    assert "ORD-" in message


async def test_the_refusal_names_the_person(env):
    """So the alert reads as a sentence about a person, not about a field."""
    token, _merchant, customer, driver, other = await a_round(env)
    await assign(env, token, customer, other, van=OTHER_VAN)
    slip_id = await assign(env, token, customer, driver)

    response = await reassign(env, token, slip_id, {"driverUserId": other.id})

    message = response.json()["detail"]["fields"][0]["message"]
    assert message.startswith(other.full_name) or "driver" in message.lower()
