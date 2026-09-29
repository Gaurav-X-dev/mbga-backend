"""The delivery app's response envelope, and the switch that controls it.

Two things worth proving, because getting either wrong is silent:

* **Off by default.** The delivery app is already signed in against the platform's raw shapes on
  the auth and notification routes. If this defaulted on, deploying it would break a working
  integration with no error anywhere - the app would simply stop finding the fields it reads.

* **Scoped to the delivery channel.** The merchant and customer apps parse
  `{"detail": {...}}` and must be untouched by a setting named after another app.
"""

from contextlib import contextmanager

import pytest

from tests.integration.deliveries.conftest import DELIVERIES, ready_to_dispatch
from tests.integration.driver.conftest import DRIVER, DRIVER_DELIVERIES, on_the_road

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


@contextmanager
def envelope_on():
    """Flip the deployment switch for part of a test.

    A context manager rather than a fixture, and that is the point: the switch has to go on
    **after** sign-in. It wraps `/delivery/auth/*` too, so a test that signs in with it already
    on cannot find `request_id` in the response - which is precisely what would happen to the
    shipped app the day this is enabled without warning its developer.

    The flag lives on `app.state` rather than in the settings dependency because middleware runs
    outside dependency resolution, so this is the same boolean a deployment sets.
    """
    from app.main import app
    from app.shared.middleware.delivery_envelope import STATE_FLAG

    previous = getattr(app.state, STATE_FLAG, False)
    setattr(app.state, STATE_FLAG, True)
    try:
        yield
    finally:
        setattr(app.state, STATE_FLAG, previous)


@pytest.fixture
def settings_overrides() -> dict:
    """The confirmation code exposed, the way a local deployment does."""
    return {"dev_expose_otp_in_response": True}


async def test_a_success_is_wrapped_for_the_delivery_app(env):
    _staff, token, slip, _driver = await on_the_road(env)

    with envelope_on():
        response = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert [row["id"] for row in body["data"]] == [slip["id"]]


async def test_an_error_carries_the_code_the_app_renders(env):
    """Without this the app's interceptor falls back to UNKNOWN_ERROR and the driver is stuck."""
    _staff_a, _token_a, slip_a, _driver_a = await on_the_road(env)
    _staff_b, token_b, _slip_b, _driver_b = await on_the_road(env)

    with envelope_on():
        response = await env.get(f"{DRIVER_DELIVERIES}/{slip_a['id']}", token_b)

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "DELIVERY_NOT_FOUND"
    assert body["error"]["statusCode"] == 404
    assert body["error"]["message"]


async def test_a_validation_error_is_still_readable(env):
    _staff, token, slip, _driver = await on_the_road(env)

    with envelope_on():
        response = await env.post(
            f"{DRIVER_DELIVERIES}/{slip['id']}/start", token, {"latitude": 999, "longitude": 0}
        )

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["message"]


async def test_the_request_id_is_still_reachable_on_the_header(env):
    """It leaves the body when the envelope is on, so support has to find it somewhere."""
    _staff, token, _slip, _driver = await on_the_road(env)

    with envelope_on():
        response = await env.get(f"{DRIVER}/profile", token)

    assert response.headers.get("X-Request-Id")


async def test_the_merchant_channel_is_untouched(env):
    """A setting named for the delivery app must not reshape anybody else's responses."""
    staff, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    with envelope_on():
        response = await env.get(f"{DELIVERIES}/{slip['id']}", staff)

    assert response.status_code == 200
    assert "success" not in response.json()
    assert response.json()["id"] == slip["id"]


class TestDefaultsOff:
    """The switch is off unless a deployment turns it on.

    This is the one that matters on deploy day: the delivery app is already integrated against
    the raw shapes, so a default of "on" would break it with no error anywhere.
    """

    async def test_the_delivery_channel_is_raw_by_default(self, env):
        _staff, token, slip, _driver = await on_the_road(env)

        response = await env.get(f"{DRIVER_DELIVERIES}/today", token)

        assert response.status_code == 200
        # A bare list, exactly as the other channels return - not wrapped.
        assert isinstance(response.json(), list)
        assert [row["id"] for row in response.json()] == [slip["id"]]
