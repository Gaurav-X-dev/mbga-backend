"""The driver's own record: who they are, whether they are working, and what is on their van.

The interesting one here is going off duty. It is the only place the app refuses something the
driver asked for, and the reason is physical rather than procedural - there are cylinders on a
road under their name.
"""

import pytest

from tests.integration.deliveries.conftest import ready_to_dispatch
from tests.integration.driver.conftest import (
    DRIVER,
    DRIVER_DELIVERIES,
    driver_token,
    on_the_road,
    patch,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


# --- Profile ---------------------------------------------------------------------------------


async def test_a_driver_reads_their_own_profile(env):
    _staff, _merchant, _order, _slip, driver = await ready_to_dispatch(env)
    token = await driver_token(env, driver)

    response = await env.get(f"{DRIVER}/profile", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == driver.id
    assert body["name"] == driver.full_name
    assert body["phone"] == driver.mobile_number
    assert body["onDuty"] is False
    assert body["avatarInitials"]


async def test_going_on_duty_sticks(env):
    _staff, _merchant, _order, _slip, driver = await ready_to_dispatch(env)
    token = await driver_token(env, driver)

    response = await patch(env, f"{DRIVER}/status", token, {"onDuty": True})

    assert response.status_code == 200, response.text
    assert response.json()["onDuty"] is True
    assert (await env.get(f"{DRIVER}/profile", token)).json()["onDuty"] is True


async def test_a_driver_cannot_sign_off_with_a_van_still_out(env):
    """Those cylinders are on the road under this driver's name.

    Letting them go off duty would leave a dispatched slip with nobody responsible for it, and
    the office would find out when the customer called.
    """
    _staff, token, _slip, _driver = await on_the_road(env)
    await patch(env, f"{DRIVER}/status", token, {"onDuty": True})

    response = await patch(env, f"{DRIVER}/status", token, {"onDuty": False})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DRIVER_HAS_ACTIVE_DELIVERIES"
    assert (await env.get(f"{DRIVER}/profile", token)).json()["onDuty"] is True


async def test_once_the_delivery_is_done_they_can_sign_off(env):
    _staff, token, slip, _driver = await on_the_road(env)
    await patch(env, f"{DRIVER}/status", token, {"onDuty": True})
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredQuantity": slip["cylindersAllocated"], "emptyCollectedQuantity": 0},
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    response = await patch(env, f"{DRIVER}/status", token, {"onDuty": False})

    assert response.status_code == 200, response.text
    assert response.json()["onDuty"] is False


# --- Van stock -------------------------------------------------------------------------------


async def test_the_van_holds_what_the_dispatched_slips_carry(env):
    """Computed from the slips, never stored - so it cannot disagree with them."""
    _staff, token, _slip, _driver = await on_the_road(env, ("LPG_19KG", 4))

    response = await env.get(f"{DRIVER}/inventory", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fullCylinderCount"] == 4
    assert body["activeDeliveries"] == 1
    assert body["fullCylinders"][0]["cylinderType"] == "LPG_19KG"
    assert body["fullCylinders"][0]["quantity"] == 4


async def test_the_van_empties_once_the_delivery_is_confirmed(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredQuantity": 4, "emptyCollectedQuantity": 2},
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    body = (await env.get(f"{DRIVER}/inventory", token)).json()

    assert body["fullCylinderCount"] == 0
    assert body["activeDeliveries"] == 0


async def test_a_driver_with_nothing_out_has_an_empty_van(env):
    _staff, _merchant, _order, _slip, driver = await ready_to_dispatch(env)
    token = await driver_token(env, driver)

    body = (await env.get(f"{DRIVER}/inventory", token)).json()

    assert body["fullCylinders"] == []
    assert body["fullCylinderCount"] == 0
    assert body["emptyCylinderCount"] == 0


async def test_one_drivers_van_never_shows_anothers_load(env):
    _staff_a, _token_a, _slip_a, _driver_a = await on_the_road(env, ("LPG_19KG", 4))
    _staff_b, token_b, _slip_b, _driver_b = await on_the_road(env, ("LPG_19KG", 2))

    body = (await env.get(f"{DRIVER}/inventory", token_b)).json()

    assert body["fullCylinderCount"] == 2
    assert body["activeDeliveries"] == 1
