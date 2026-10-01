"""The driver endpoints are guarded by permission as well as by scope.

Two different questions, and both have to be answered:

* **Scope** - `driver_user_id` decides *which* deliveries are yours. That is what makes another
  driver's slip a `404`, and it is enforced in every query's `WHERE`.
* **Permission** - `deliveries.view` and `deliveries.update_status` decide whether you may work
  at all. Both are seeded onto the `driver` and `helper` roles, so nothing is granted per
  deployment; taking the role away is how a merchant stops someone using the app without
  touching a single slip.

Without the test below the permission guard would be decoration: it would sit in the code, pass
every test because every test driver happens to hold the role, and nobody would notice if it
stopped being enforced.
"""

import pytest
from sqlalchemy import delete, update

from app.modules.users.role_models import UserRole
from tests.integration.driver.conftest import DRIVER, DRIVER_DELIVERIES, on_the_road, patch

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def _strip_roles(env, user_id: str) -> None:
    """Take every role off this driver, leaving the account itself active."""
    await env.execute(delete(UserRole).where(UserRole.user_id == user_id))


async def test_a_driver_without_the_role_cannot_read_their_queue(env):
    _staff, token, _slip, driver = await on_the_road(env)
    await _strip_roles(env, driver.id)

    response = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    assert response.status_code == 403, response.text


async def test_a_driver_without_the_role_cannot_complete_a_handover(env):
    """The one that matters: stock moves here, so the guard has to hold on the write path too."""
    _staff, token, slip, driver = await on_the_road(env)
    await _strip_roles(env, driver.id)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredQuantity": slip["cylindersAllocated"], "emptyCollectedQuantity": 0},
    )

    assert response.status_code == 403, response.text


async def test_a_driver_without_the_role_cannot_go_on_duty(env):
    _staff, token, _slip, driver = await on_the_road(env)
    await _strip_roles(env, driver.id)

    response = await patch(env, f"{DRIVER}/status", token, {"onDuty": True})

    assert response.status_code == 403, response.text


async def test_an_inactive_role_assignment_is_not_enough(env):
    """A revoked assignment left in the table must not still authorise.

    Roles are deactivated rather than deleted in some flows, and a guard that read the row
    without checking `is_active` would keep letting a stood-down driver work.
    """
    _staff, token, _slip, driver = await on_the_road(env)
    await env.execute(
        update(UserRole).where(UserRole.user_id == driver.id).values(is_active=False)
    )

    response = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    assert response.status_code == 403, response.text


async def test_the_seeded_driver_role_is_enough_on_its_own(env):
    """Nothing has to be granted per deployment - the base RBAC seed already covers a driver."""
    _staff, token, slip, _driver = await on_the_road(env)

    listed = await env.get(f"{DRIVER_DELIVERIES}/today", token)
    started = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-location", token, {"latitude": 26.45, "longitude": 80.33}
    )

    assert listed.status_code == 200, listed.text
    assert started.status_code == 200, started.text
