"""Who the office may put on a van, and who the assignment endpoint refuses.

Two layers, deliberately not the same rules:

* **The dropdown** (`/delivery-users/available`) answers "who can take a job right now", so it
  filters on duty as well. It is advisory - two people can be shown the same free driver.
* **The assignment** re-checks under a lock and decides. It does *not* require on duty, because
  that is the driver's own live toggle and tomorrow's round is planned this evening, when every
  driver is off shift.

The pair that matters is the double-booking: both screens offer the same driver, both press Save,
and only one slip may exist.
"""

import pytest
from sqlalchemy import update

from app.modules.delivery_users.models import DeliveryProfile
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    MERCHANT,
    code_of,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    ready_to_dispatch,
    refill,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

AVAILABLE = f"{MERCHANT}/delivery-users/available"


async def set_duty(env, user, on: bool) -> None:
    await env.execute(
        update(DeliveryProfile).where(DeliveryProfile.user_id == user.id).values(on_duty=on)
    )


def ids(response) -> set[str]:
    return {row["user_id"] for row in response.json()["items"]}


# --- The dropdown ----------------------------------------------------------------------------


async def test_an_on_duty_driver_is_offered(env):
    token, merchant, _user = await dispatch_staff(env)
    driver = await make_driver(env, merchant)
    await set_duty(env, driver, True)

    response = await env.get(AVAILABLE, token)

    assert response.status_code == 200, response.text
    assert driver.id in ids(response)


async def test_an_off_duty_driver_is_not_offered(env):
    """Not a rule about validity - just not someone who can take a job this minute."""
    token, merchant, _user = await dispatch_staff(env)
    driver = await make_driver(env, merchant)
    await set_duty(env, driver, False)

    response = await env.get(AVAILABLE, token)

    assert driver.id not in ids(response)


async def test_a_blocked_driver_is_not_offered(env):
    token, merchant, _user = await dispatch_staff(env)
    driver = await make_driver(env, merchant, status="BLOCKED")
    await set_duty(env, driver, True)

    response = await env.get(AVAILABLE, token)

    assert driver.id not in ids(response)


async def test_a_driver_already_carrying_a_slip_is_not_offered(env):
    """The van is spoken for from the moment the office assigns it, not from dispatch."""
    token, _merchant, _order, _slip, driver = await ready_to_dispatch(env)
    await set_duty(env, driver, True)

    response = await env.get(AVAILABLE, token)

    assert driver.id not in ids(response)


async def test_helpers_are_a_separate_list(env):
    token, merchant, _user = await dispatch_staff(env)
    driver = await make_driver(env, merchant)
    helper, _m, _p = await env.create_delivery_user(merchant, kind="HELPER")
    await set_duty(env, driver, True)
    await set_duty(env, helper, True)

    # snake_case, matching the query names the rest of this router already publishes.
    drivers = await env.get(f"{AVAILABLE}?delivery_user_type=DRIVER", token)
    helpers = await env.get(f"{AVAILABLE}?delivery_user_type=HELPER", token)

    assert driver.id in ids(drivers) and driver.id not in ids(helpers)
    assert helper.id in ids(helpers) and helper.id not in ids(drivers)


async def test_another_merchants_driver_is_never_offered(env):
    token, _merchant, _user = await dispatch_staff(env)
    other_driver, _other_merchant, _p = await env.create_delivery_user()
    await set_duty(env, other_driver, True)

    response = await env.get(AVAILABLE, token)

    assert other_driver.id not in ids(response)


# --- The assignment --------------------------------------------------------------------------


async def test_a_driver_can_be_assigned_while_off_duty(env):
    """Tomorrow's round is planned this evening, when nobody is on shift."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 60)
    order = await place_order(env, token, customer.id)
    driver = await make_driver(env, merchant)
    await set_duty(env, driver, False)

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 0001", "driverUserId": driver.id},
    )

    assert response.status_code == 201, response.text


async def test_a_driver_already_on_a_slip_cannot_take_another(env):
    """Both screens offered the same free driver; only one of them may win."""
    token, merchant, _order, _slip, driver = await ready_to_dispatch(env)
    customer = await make_customer(env, merchant)
    second = await place_order(env, token, customer.id)

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": second["id"], "vehicleNumber": "MP09 GH 0002", "driverUserId": driver.id},
    )

    assert response.status_code == 422, response.text
    assert code_of(response) == "VALIDATION_ERROR"
    fields = {field["code"] for field in response.json()["detail"]["fields"]}
    assert "driver_already_assigned" in fields


async def test_a_helper_already_on_a_slip_cannot_take_another(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 60)
    helper, _m, _p = await env.create_delivery_user(merchant, kind="HELPER")

    first = await place_order(env, token, customer.id)
    taken = await env.post(
        DELIVERIES,
        token,
        {
            "orderId": first["id"],
            "vehicleNumber": "MP09 GH 0003",
            "driverName": "Hired van driver",
            "helperUserId": helper.id,
        },
    )
    assert taken.status_code == 201, taken.text

    second = await place_order(env, token, customer.id)
    response = await env.post(
        DELIVERIES,
        token,
        {
            "orderId": second["id"],
            "vehicleNumber": "MP09 GH 0004",
            "driverName": "Hired van driver",
            "helperUserId": helper.id,
        },
    )

    assert response.status_code == 422, response.text
    fields = {field["code"] for field in response.json()["detail"]["fields"]}
    assert "helper_already_assigned" in fields


async def test_a_driver_freed_by_a_failed_slip_can_be_assigned_again(env):
    """A van that comes back releases its crew, or one failed delivery benches them for good."""
    token, merchant, _order, slip, driver = await ready_to_dispatch(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Van broke down"})
    customer = await make_customer(env, merchant)
    second = await place_order(env, token, customer.id)

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": second["id"], "vehicleNumber": "MP09 GH 0005", "driverUserId": driver.id},
    )

    assert response.status_code == 201, response.text
