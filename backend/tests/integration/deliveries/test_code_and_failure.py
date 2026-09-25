"""The proof-of-delivery code, and the slip that never delivered.

The code is what separates "the driver says it was delivered" from "the customer says it was
received", so the tests here are about the things that would quietly undermine it: a mock code
that works in production, a code readable out of the table, an attempt budget that never counts
down, a code that still verifies after the slip is settled.

The failure tests cover the other half of the spec's `DeliveryStatus` - `FAILED` is in the enum
and on the list filter, and a dispatched slip that comes back loaded has real stock sitting on a
van that has to go somewhere.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.constants import MAX_CODE_ATTEMPTS
from app.modules.deliveries.models import DeliverySlip
from app.modules.inventory.models import StockMovement
from app.shared.notifications.models import NotificationOutbox
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    code_of,
    counts,
    ready_to_dispatch,
    slip_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def on_the_road(env, **kwargs):
    """A dispatched slip and its code."""
    token, merchant, order, slip, driver = await ready_to_dispatch(env, **kwargs)
    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)
    assert response.status_code == 200, response.text
    body = response.json()
    return token, merchant, order, body, driver, body["devConfirmationCode"]


async def notifications_for(env, recipient_id: str) -> list[tuple[str, str, str]]:
    rows = list(
        await env.execute(
            select(NotificationOutbox.event_type, NotificationOutbox.title, NotificationOutbox.body)
            .where(NotificationOutbox.recipient_id == recipient_id)
        )
    )
    return [(row.event_type, row.title, row.body) for row in rows]


# --- The code reaches the customer ---------------------------------------------------------------


async def test_the_code_is_minted_at_dispatch_not_before(env):
    """A slip raised the evening before should not carry a live code all night."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    before = await env.scalar(
        select(DeliverySlip.confirmation_code_hash).where(DeliverySlip.id == slip["id"])
    )
    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)
    after = await env.scalar(
        select(DeliverySlip.confirmation_code_hash).where(DeliverySlip.id == slip["id"])
    )

    assert before is None
    assert after is not None


async def test_the_customer_is_told_the_code(env):
    """The only channel that carries it. Without this the driver asks for digits nobody sent."""
    _token, _merchant, order, _slip, _driver, code = await on_the_road(env)

    events = await notifications_for(env, order["customerId"])

    dispatch_body = next(body for event, _title, body in events if event == "DELIVERY_DISPATCHED")
    assert f"Share code {code} with the driver." in dispatch_body
    assert "has left the godown" in dispatch_body


async def test_the_code_is_never_stored_in_the_clear(env):
    """A plain column would be a live shared secret the whole office could query."""
    _token, _merchant, _order, slip, _driver, code = await on_the_road(env)

    stored = await env.scalar(
        select(DeliverySlip.confirmation_code_hash).where(DeliverySlip.id == slip["id"])
    )

    assert code not in stored
    assert stored.startswith("$pbkdf2-sha256$")


async def test_the_real_code_confirms_the_delivery(env):
    token, _merchant, _order, slip, _driver, code = await on_the_road(env)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 1}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DELIVERED"


# --- Wrong codes ----------------------------------------------------------------------------------


async def test_a_wrong_code_spends_an_attempt(env):
    """Committed on its own, or the count resets on every retry and the budget is fiction."""
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)

    for _ in range(3):
        refused = await env.post(
            f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "0000", "emptiesCollected": 0}
        )
        assert refused.status_code == 422

    attempts = await env.scalar(
        select(DeliverySlip.confirmation_attempts).where(DeliverySlip.id == slip["id"])
    )
    assert attempts == 3


async def test_a_malformed_code_costs_no_attempt(env):
    """A letter in the box is a typo, not a guess - and nothing is hashed for it."""
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)

    refused = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "abcd", "emptiesCollected": 0}
    )

    assert refused.status_code == 422
    attempts = await env.scalar(
        select(DeliverySlip.confirmation_attempts).where(DeliverySlip.id == slip["id"])
    )
    assert attempts == 0


async def test_a_missing_code_is_refused_when_the_method_is_otp(env):
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)

    refused = await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"emptiesCollected": 0})

    assert refused.status_code == 422
    assert refused.json()["detail"]["fields"][0]["field"] == "otp"


async def test_the_slip_locks_after_too_many_wrong_codes(env):
    """Generous, because a misheard digit at a noisy gate is the common case."""
    token, _merchant, _order, slip, _driver, code = await on_the_road(env)
    for _ in range(MAX_CODE_ATTEMPTS):
        await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "0000", "emptiesCollected": 0})

    # Even the right code is refused now: the office has to take over.
    locked = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 0}
    )

    assert locked.status_code == 409
    assert code_of(locked) == "DELIVERY_CODE_LOCKED"
    assert (await slip_of(env, token, slip["id"]))["status"] == "DISPATCHED"


async def test_one_slips_code_does_not_confirm_another(env):
    """Codes are four digits, so they collide across slips by design - the hash is per slip.

    Both slips belong to the same merchant here, deliberately: a cross-tenant attempt is already a
    404 on the slip, which would hide whether the code check itself is per slip.
    """
    from tests.integration.deliveries.conftest import make_customer, place_order

    token, merchant, _order, first, _driver = await ready_to_dispatch(env)
    customer = await make_customer(env, merchant)
    from tests.integration.deliveries.conftest import refill

    await refill(env, token, quantity=60)
    other_order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    created = await env.post(
        DELIVERIES,
        token,
        {"orderId": other_order["id"], "vehicleNumber": "MP09 GH 4522", "driverName": "Arjun"},
    )
    assert created.status_code == 201, created.text
    second = created.json()

    first_code = (await env.post(f"{DELIVERIES}/{first['id']}/dispatch", token)).json()["devConfirmationCode"]
    second_code = (await env.post(f"{DELIVERIES}/{second['id']}/dispatch", token)).json()["devConfirmationCode"]
    if first_code == second_code:
        pytest.skip("the two slips happened to mint the same four digits")

    crossed = await env.post(
        f"{DELIVERIES}/{second['id']}/confirm", token, {"otp": first_code, "emptiesCollected": 0}
    )

    assert crossed.status_code == 422
    assert (await slip_of(env, token, second["id"]))["status"] == "DISPATCHED"


# --- Production posture ----------------------------------------------------------------------------


class TestWithoutTheDevSwitch:
    """A deployment configured the way production is: no codes in responses.

    The spec says the mock accepts `4321`, and the module honours that - but only behind the same
    switch that already exposes login OTPs. A fixed code that worked in production would let anyone
    who read the spec confirm any delivery.
    """

    @pytest.fixture
    def settings_overrides(self) -> dict:
        return {"dev_expose_otp_in_response": False}

    async def test_the_code_is_not_returned(self, env):
        token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

        response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

        assert response.status_code == 200
        assert response.json()["devConfirmationCode"] is None

    async def test_the_mock_code_is_refused(self, env):
        token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
        await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

        response = await env.post(
            f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": "4321", "emptiesCollected": 0}
        )

        assert response.status_code == 422
        assert response.json()["detail"]["fields"][0]["message"] == "Incorrect OTP"
        assert (await slip_of(env, token, slip["id"]))["status"] == "DISPATCHED"

    async def test_the_customer_still_gets_the_code_in_their_notification(self, env):
        """It is the only channel, so it must work with the switch off - that is the point."""
        token, _merchant, order, slip, _driver = await ready_to_dispatch(env)

        await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

        bodies = [body for event, _title, body in await notifications_for(env, order["customerId"]) if event == "DELIVERY_DISPATCHED"]
        assert "Share code" in bodies[0]


# --- A slip that never delivered ---------------------------------------------------------------------


async def test_failing_a_dispatched_slip_returns_the_stock(env):
    """The cylinders came back on the van, so they come back on the books."""
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)
    assert await counts(env, token) == (56, 0, 0)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Customer refused - wrong address"}
    )

    assert response.status_code == 200, response.text
    failed = response.json()
    assert failed["status"] == "FAILED"
    assert failed["failureReason"] == "Customer refused - wrong address"
    assert await counts(env, token) == (60, 0, 0), "back on the shelf"


async def test_the_return_is_booked_against_the_slip(env):
    """A correction would say "the register was wrong". This says where the cylinders went."""
    token, merchant, _order, slip, _driver, _code = await on_the_road(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    rows = list(
        await env.execute(
            select(StockMovement.movement_type, StockMovement.reference_type, StockMovement.note)
            .where(StockMovement.merchant_id == merchant.id, StockMovement.reference_id == slip["id"])
        )
    )
    types = {(row.movement_type, row.reference_type) for row in rows}
    assert ("DISPATCHED", "DELIVERY") in types
    assert ("RECEIVED_FILLED", "DELIVERY") in types
    assert any(row.note == "Returned undelivered" for row in rows)


async def test_stock_left_with_the_customer_is_not_returned(env):
    """`returnedToStock: false` - the cylinders are out there and the office has to resolve it."""
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)

    await env.post(
        f"{DELIVERIES}/{slip['id']}/fail",
        token,
        {"reason": "Left at the shop, no one to sign", "returnedToStock": False},
    )

    assert await counts(env, token) == (56, 0, 0), "still out"


async def test_failing_a_scheduled_slip_moves_no_stock(env):
    """Nothing ever left, so there is nothing to bring back."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    response = await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Van broke down"})

    assert response.status_code == 200
    assert await counts(env, token) == (60, 0, 0)


async def test_staff_are_told_a_delivery_failed(env):
    """It needs an internal decision before the customer is told anything (spec §18.8)."""
    token, merchant, _order, slip, _driver, _code = await on_the_road(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    events = await notifications_for(env, merchant.id)
    assert any(event == "DELIVERY_FAILED" and title == "Delivery failed" for event, title, _b in events)


async def test_the_driver_is_told_the_job_is_off_them(env):
    """A driver acting on a stale job loads a van for a delivery nobody is making."""
    token, _merchant, _order, slip, driver, _code = await on_the_road(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Van broke down"})

    events = await notifications_for(env, driver.id)
    assert any(event == "DELIVERY_UNASSIGNED" for event, _t, _b in events)


async def test_a_failed_slips_code_is_spent(env):
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)

    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    stored = await env.scalar(
        select(DeliverySlip.confirmation_code_hash).where(DeliverySlip.id == slip["id"])
    )
    assert stored is None


async def test_a_delivered_slip_cannot_be_failed(env):
    """A delivered slip is a receipt."""
    token, _merchant, _order, slip, _driver, code = await on_the_road(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 0})

    response = await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Changed my mind"})

    assert response.status_code == 409
    assert code_of(response) == "DELIVERY_ALREADY_SETTLED"


async def test_a_failed_slip_cannot_be_failed_again(env):
    """Otherwise the stock comes back twice."""
    token, _merchant, _order, slip, _driver, _code = await on_the_road(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    again = await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    assert again.status_code == 409
    assert await counts(env, token) == (60, 0, 0), "returned once"


async def test_a_failed_slip_cannot_be_dispatched(env):
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Van broke down"})

    response = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)

    assert response.status_code == 409
    assert "Raise a new slip" in response.json()["detail"]["message"]


async def test_a_failed_slip_cannot_be_confirmed(env):
    token, _merchant, _order, slip, _driver, code = await on_the_road(env)
    await env.post(f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Shop closed"})

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", token, {"otp": code, "emptiesCollected": 0}
    )

    assert response.status_code == 409
