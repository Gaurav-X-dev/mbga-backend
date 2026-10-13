"""Loading a van through the morning, and after it has left.

A round is filled one order at a time: the office assigns a drop, then another, then another,
all onto the same van for the same day. Treating the first assignment as a booking made that
impossible - a driver with one order could not be given a second, and the availability list
dropped him the moment he had any work at all.

Leaving the godown does not end it either. A van goes out carrying more than the round it left
with, so an order that arrives mid-morning is served off what is already loaded: the office adds
it, the driver sees it on his list, and takes it on the same run. Refusing it would send a
second van out for cylinders the first one is already carrying.

What still refuses is a *different* round - another vehicle, or another day. That is not more
work for this van; it is one person being sent two places.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.shared.date_time.business_calendar import business_today

from app.modules.deliveries.models import DeliverySlip
from tests.integration.driver.conftest import DRIVER_DELIVERIES, driver_token
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

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

DELIVERY_USERS = "/api/v1/merchant/delivery-users"
VAN = "MP09 GH 4521"


async def a_round(env):
    """Staff, a stocked merchant, a customer and a driver - ready to be given work."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 400)
    driver = await make_driver(env, merchant)
    return token, merchant, customer, driver


async def assign(env, token, customer, driver, *, quantity=2, van=VAN, date=None):
    """Place an order and confirm it onto this driver's van, today unless told otherwise."""
    order = await place_order(env, token, customer.id, ("LPG_19KG", quantity))
    delivery = {"vehicleNumber": van, "driverUserId": driver.id}
    if date is not None:
        delivery["deliveryDate"] = date.isoformat()
    return await env.post(f"{ORDERS}/{order['id']}/confirm", token, {"delivery": delivery})


async def available(env, token, *, kind="DRIVER"):
    response = await env.get(f"{DELIVERY_USERS}/available?delivery_user_type={kind}", token)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def go_out(env, driver, confirmed):
    """Send the van out, through the driver's own app - the only way one leaves now."""
    slip_id = confirmed.json()["deliverySlipId"]
    token = await driver_token(env, driver)
    response = await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", token, {})
    assert response.status_code == 200, response.text
    return slip_id


async def clock_on(env, driver) -> None:
    """The availability list only offers crew who have clocked on."""
    from sqlalchemy import update

    from app.modules.delivery_users.models import DeliveryProfile

    await env.execute(
        update(DeliveryProfile).where(DeliveryProfile.user_id == driver.id).values(on_duty=True)
    )


# --- Filling the van ------------------------------------------------------------------------


async def test_a_driver_takes_a_second_order(env):
    token, _merchant, customer, driver = await a_round(env)
    first = await assign(env, token, customer, driver)
    assert first.status_code == 200, first.text

    second = await assign(env, token, customer, driver)

    assert second.status_code == 200, second.text
    assert second.json()["deliverySlipId"] != first.json()["deliverySlipId"]


async def test_he_stays_in_the_assignment_list_while_he_is_carrying_work(env):
    token, _merchant, customer, driver = await a_round(env)
    await clock_on(env, driver)
    await assign(env, token, customer, driver)

    assert driver.id in {item["user_id"] for item in await available(env, token)}


# --- After the van has left -----------------------------------------------------------------


async def test_a_dispatched_driver_still_takes_a_new_order(env):
    """Served off the cylinders already on the van, which is why he is the right person for it."""
    token, _merchant, customer, driver = await a_round(env)
    await go_out(env, driver, await assign(env, token, customer, driver))

    later = await assign(env, token, customer, driver)

    assert later.status_code == 200, later.text


async def test_a_dispatched_driver_stays_in_the_assignment_list(env):
    token, _merchant, customer, driver = await a_round(env)
    await clock_on(env, driver)
    await go_out(env, driver, await assign(env, token, customer, driver))

    assert driver.id in {item["user_id"] for item in await available(env, token)}


async def test_the_new_order_reaches_the_driver_who_is_already_out(env):
    """It is no use being assignable if the drop never appears on his phone."""
    token, _merchant, customer, driver = await a_round(env)
    await go_out(env, driver, await assign(env, token, customer, driver))
    later = await assign(env, token, customer, driver)

    token_d = await driver_token(env, driver)
    today = await env.get(f"{DRIVER_DELIVERIES}/today", token_d)

    assert later.json()["deliverySlipId"] in {row["id"] for row in today.json()}


async def test_the_driver_can_take_the_added_order_out_as_well(env):
    """He presses Out For Delivery on the new drop without returning to the godown."""
    token, _merchant, customer, driver = await a_round(env)
    await go_out(env, driver, await assign(env, token, customer, driver))
    later = await assign(env, token, customer, driver)

    slip_id = await go_out(env, driver, later)

    status = await env.scalar(select(DeliverySlip.status).where(DeliverySlip.id == slip_id))
    assert status in {"DISPATCHED", "ON_LOCATION"}


# --- What is still a conflict ---------------------------------------------------------------


async def test_a_second_vehicle_on_the_same_day_is_refused(env):
    """Not more work for this van - one person sent two places."""
    token, _merchant, customer, driver = await a_round(env)
    await assign(env, token, customer, driver)

    elsewhere = await assign(env, token, customer, driver, van="MP09 ZZ 0001")

    assert elsewhere.status_code == 422, elsewhere.text
    assert elsewhere.json()["detail"]["fields"][0]["code"] == "driver_already_assigned"


async def test_tomorrows_round_can_be_planned_while_today_is_still_open(env):
    """The evening's planning happens before the day's last delivery is confirmed. Comparing
    against every live slip blocked a driver from all of next week until it was."""
    token, _merchant, customer, driver = await a_round(env)
    await go_out(env, driver, await assign(env, token, customer, driver))

    tomorrow = await assign(
        env, token, customer, driver, van="HR00052", date=business_today() + timedelta(days=1)
    )

    assert tomorrow.status_code == 200, tomorrow.text


async def test_a_driver_who_has_clocked_off_is_not_offered(env):
    """The one thing that still hides a name, and the response says why."""
    token, _merchant, _customer, driver = await a_round(env)

    assert driver.id not in {item["user_id"] for item in await available(env, token)}
    rows = (await env.get(f"{DELIVERY_USERS}?delivery_user_type=DRIVER", token)).json()["items"]
    assert next(item for item in rows if item["user_id"] == driver.id)["on_duty"] is False


async def test_the_dropdown_still_asks_for_the_right_kind_of_crew(env):
    """A helper is not a driver, and offering one in the driver slot is an assignment that fails."""
    token, _merchant, _customer, driver = await a_round(env)
    await clock_on(env, driver)

    helpers = await available(env, token, kind="HELPER")

    assert driver.id not in {item["user_id"] for item in helpers}


async def test_the_slip_for_each_order_is_its_own(env):
    """A round is several slips on one van, not one slip gathering orders."""
    token, _merchant, customer, driver = await a_round(env)
    await assign(env, token, customer, driver)
    await assign(env, token, customer, driver)

    async with env.sessions() as db:
        slips = list(
            await db.scalars(select(DeliverySlip).where(DeliverySlip.driver_user_id == driver.id))
        )
    assert len(slips) == 2
    assert {slip.vehicle_number for slip in slips} == {VAN}
