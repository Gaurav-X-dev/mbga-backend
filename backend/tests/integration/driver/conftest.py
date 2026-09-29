"""Fixtures for the delivery app's own endpoints.

Builds on the dispatch suite: a driver only has work once the office has raised a slip for them
and sent the van out, so these helpers drive the merchant endpoints to get there and then hand
back a **driver** token for the delivery channel.
"""

import pytest
from sqlalchemy import update

from app.modules.deliveries.models import DeliverySlip

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)
from tests.integration.deliveries.conftest import (  # noqa: F401
    DELIVERIES,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    ready_to_dispatch,
    refill,
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

DELIVERY_AUTH = "/api/v1/delivery/auth"
DRIVER_DELIVERIES = "/api/v1/delivery/deliveries"
DRIVER = "/api/v1/delivery/driver"


async def patch(auth_env, path: str, token: str, json: dict):
    """`AuthEnv` has get and post but no patch, and the delivery app uses PATCH for the driver's
    own settings. Added here rather than in the authentication conftest, which this package
    imports and never edits."""
    return await auth_env.client.patch(
        path, headers={"Authorization": f"Bearer {token}"}, json=json
    )


async def driver_token(auth_env, driver) -> str:
    """Sign the driver in on their own channel."""
    session = await auth_env.sign_in(DELIVERY_AUTH, driver.mobile_number)
    return session["token"]["access_token"]


async def on_the_road(auth_env, *lines, quantity: int = 60):
    """A dispatched slip with a signed-in driver behind it.

    Returns `(staff_token, drivers_token, slip, driver)`. This is the state the app is in when a
    driver opens it: cylinders on the van, nothing handed over yet.
    """
    staff_token, _merchant, _order, slip, driver = await ready_to_dispatch(
        auth_env, *lines, quantity=quantity
    )
    dispatched = await auth_env.post(f"{DELIVERIES}/{slip['id']}/dispatch", staff_token, {})
    assert dispatched.status_code == 200, dispatched.text
    return staff_token, await driver_token(auth_env, driver), dispatched.json(), driver


async def give_site_coordinates(auth_env, slip, latitude: float, longitude: float) -> None:
    """Record where the van is being sent, so the geofence has something to measure against.

    Written onto the slip, which is where a real one gets it - copied off a named delivery site
    when the slip is raised. Most orders go to the customer's registered address and carry no
    coordinates at all, which is its own test below.
    """
    await auth_env.execute(
        update(DeliverySlip)
        .where(DeliverySlip.id == slip["id"])
        .values(destination_latitude=latitude, destination_longitude=longitude)
    )
