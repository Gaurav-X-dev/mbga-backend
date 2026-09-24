"""Draining the outbox to FCM.

Firebase is stubbed. What is being tested is the dispatcher's judgement, not Google's:
which devices a queued event resolves to, what counts as delivered, which failures are worth
retrying and which token should be forgotten. Those are the decisions that decide whether a
customer gets told their order was placed.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.authentication.models import LoginSession
from app.modules.notifications.dispatcher import MAX_ATTEMPTS, NotificationDispatcher
from app.modules.notifications.fcm import PushMessage, SendResult
from app.shared.notifications.models import NotificationOutbox
from tests.integration.notifications.conftest import customer, queue, staff

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


class StubFcm:
    """Records what would have been sent, and answers however the test needs."""

    def __init__(self, result: SendResult | None = None) -> None:
        self.result = result or SendResult(ok=True)
        self.sent: list[tuple[str, PushMessage]] = []
        self.results_by_token: dict[str, SendResult] = {}

    async def send(self, token: str, message: PushMessage) -> SendResult:
        self.sent.append((token, message))
        return self.results_by_token.get(token, self.result)

    @property
    def tokens(self) -> list[str]:
        return [token for token, _ in self.sent]


async def _dispatch(env, client, *, now: datetime | None = None):
    async with env.sessions() as session:
        return await NotificationDispatcher(session, client).run(now=now)


async def _row(env, notification_id: str) -> NotificationOutbox:
    return await env.scalar(select(NotificationOutbox).where(NotificationOutbox.id == notification_id))


# --- Resolving devices ------------------------------------------------------------------------


async def test_a_customer_event_reaches_that_customers_device(env):
    _staff_token, merchant, _u = await staff(env)
    _token, profile, _user = await customer(env, merchant, fcm_token="cust-device-1")
    notification_id = await queue(env, recipient_kind="customer", recipient_id=profile.id)
    fcm = StubFcm()

    report = await _dispatch(env, fcm)

    assert fcm.tokens == ["cust-device-1"]
    assert report.delivered == 1
    assert (await _row(env, notification_id)).delivered_at is not None


async def test_a_merchant_event_reaches_every_staff_device(env):
    """Spec §15: all staff share the merchant bucket, so all of them are notified."""
    _manager, merchant, _u1 = await staff(env, fcm_token="manager-device")
    _colleague, _same, _u2 = await staff(env, merchant, fcm_token="colleague-device")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()

    report = await _dispatch(env, fcm)

    assert sorted(fcm.tokens) == ["colleague-device", "manager-device"]
    assert report.delivered == 1


async def test_another_merchants_staff_are_not_notified(env):
    _ours, our_merchant, _u1 = await staff(env, fcm_token="ours")
    _theirs, _their_merchant, _u2 = await staff(env, fcm_token="theirs")
    await queue(env, recipient_kind="merchant", recipient_id=our_merchant.id)
    fcm = StubFcm()

    await _dispatch(env, fcm)

    assert fcm.tokens == ["ours"]


async def test_one_device_with_several_live_sessions_is_sent_to_once(env):
    """A refresh leaves the old session behind; the user must not see two notifications."""
    _token, merchant, _u = await staff(env, fcm_token="same-phone")
    # Sign in again on the same device, which leaves two live sessions holding the token.
    await staff(env, merchant, fcm_token="same-phone")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()

    await _dispatch(env, fcm)

    assert fcm.tokens == ["same-phone"]


async def test_a_signed_out_device_is_not_notified(env):
    """Signing out revokes the session and clears its token, so the device drops out here."""
    _token, merchant, _u = await staff(env, fcm_token="going-away")
    # What logout does, applied directly: this test is about the dispatcher, not the auth
    # contract, and going through the logout endpoint would test that instead.
    await env.execute(
        LoginSession.__table__.update()
        .where(LoginSession.__table__.c.push_token == "going-away")
        .values(revoked_at=datetime.now(UTC).replace(tzinfo=None), push_token=None)
    )
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()

    report = await _dispatch(env, fcm)

    assert fcm.sent == []
    assert report.no_devices == 1


async def test_a_revoked_session_that_still_holds_a_token_is_skipped(env):
    """Belt and braces: the query filters on `revoked_at`, not only on the token."""
    _token, merchant, _u = await staff(env, fcm_token="stale")
    await env.execute(
        LoginSession.__table__.update()
        .where(LoginSession.__table__.c.push_token == "stale")
        .values(revoked_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()

    await _dispatch(env, fcm)

    assert fcm.sent == []


async def test_a_row_with_no_device_is_settled_not_retried_forever(env):
    """Nobody is signed in; the in-app list still carries it, which is where it gets read."""
    _token, merchant, _u = await staff(env)  # no fcm_token
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()

    report = await _dispatch(env, fcm)

    assert report.no_devices == 1
    row = await _row(env, notification_id)
    assert row.delivered_at is not None
    assert row.attempts == 0


# --- The payload -------------------------------------------------------------------------------


async def test_the_push_carries_the_deep_link_as_data(env):
    _staff_token, merchant, _u = await staff(env)
    _token, profile, _user = await customer(env, merchant, fcm_token="dev")
    await queue(env, recipient_kind="customer", recipient_id=profile.id,
                event_type="ORDER_PLACED", entity_type="order", entity_id="ord-9",
                title="Order placed", body="Order ORD-2609-0001 has been placed.")
    fcm = StubFcm()

    await _dispatch(env, fcm)

    _token_sent, message = fcm.sent[0]
    assert message.title == "Order placed"
    assert message.body == "Order ORD-2609-0001 has been placed."
    # The app routes on these rather than parsing the title.
    assert message.data["referenceType"] == "ORDER"
    assert message.data["referenceId"] == "ord-9"
    assert message.data["category"] == "ORDER"
    # Every value must be a string or FCM rejects the map.
    assert all(isinstance(value, str) for value in message.data.values())


# --- Failure handling ----------------------------------------------------------------------------


async def test_a_network_failure_is_retried_with_a_back_off(env):
    _token, merchant, _u = await staff(env, fcm_token="dev")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm(SendResult(ok=False, error="network: ConnectError"))

    report = await _dispatch(env, fcm)

    assert report.retrying == 1
    row = await _row(env, notification_id)
    assert row.delivered_at is None
    assert row.attempts == 1
    assert row.next_attempt_at is not None
    assert "network" in row.last_error


async def test_a_row_is_not_retried_before_its_back_off_elapses(env):
    _token, merchant, _u = await staff(env, fcm_token="dev")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm(SendResult(ok=False, error="boom"))
    await _dispatch(env, fcm)

    # Immediately again: the back-off has not passed, so nothing is even considered.
    second = await _dispatch(env, StubFcm(SendResult(ok=False, error="boom")))

    assert second.considered == 0


async def test_a_row_is_abandoned_after_its_attempts_run_out(env):
    """One poisoned row must not hold up the queue forever - but it stays visible."""
    _token, merchant, _u = await staff(env, fcm_token="dev")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    moment = datetime.now(UTC)

    for attempt in range(MAX_ATTEMPTS):
        # Step past each back-off rather than waiting it out.
        await _dispatch(env, StubFcm(SendResult(ok=False, error="boom")), now=moment + timedelta(hours=4 * attempt))

    row = await _row(env, notification_id)
    assert row.attempts == MAX_ATTEMPTS
    assert row.delivered_at is None
    assert row.last_error == "boom"
    # Nothing picks it up again.
    assert (await _dispatch(env, StubFcm(), now=moment + timedelta(days=1))).considered == 0


async def test_a_dead_token_is_forgotten_rather_than_retried(env):
    """Retrying a retired device forever is how an outbox stops draining."""
    _token, merchant, _u = await staff(env, fcm_token="uninstalled")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm(SendResult(ok=False, token_dead=True, error="404: UNREGISTERED"))

    report = await _dispatch(env, fcm)

    assert report.tokens_forgotten == 1
    # Settled, not left to retry: that device will never accept it.
    assert (await _row(env, notification_id)).delivered_at is not None
    live = list(await env.execute(select(LoginSession.push_token).where(LoginSession.push_token == "uninstalled")))
    assert live == [], "the dead token is cleared from the session"


async def test_one_dead_device_does_not_stop_the_others(env):
    _manager, merchant, _u1 = await staff(env, fcm_token="good-device")
    _colleague, _same, _u2 = await staff(env, merchant, fcm_token="dead-device")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()
    fcm.results_by_token["dead-device"] = SendResult(ok=False, token_dead=True, error="404")

    report = await _dispatch(env, fcm)

    assert report.delivered == 1
    assert report.tokens_forgotten == 1
    assert (await _row(env, notification_id)).delivered_at is not None


async def test_one_live_device_succeeding_settles_the_row(env):
    _manager, merchant, _u1 = await staff(env, fcm_token="reachable")
    _colleague, _same, _u2 = await staff(env, merchant, fcm_token="unreachable")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    fcm = StubFcm()
    fcm.results_by_token["unreachable"] = SendResult(ok=False, error="network")

    report = await _dispatch(env, fcm)

    assert report.delivered == 1
    assert (await _row(env, notification_id)).delivered_at is not None


# --- Switched off ----------------------------------------------------------------------------------


async def test_with_push_off_rows_stay_queued_rather_than_being_lost(env):
    """Turning Firebase on later must deliver the backlog, not skip it."""
    _token, merchant, _u = await staff(env, fcm_token="dev")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    report = await _dispatch(env, None)

    assert report.retrying == 1
    row = await _row(env, notification_id)
    assert row.delivered_at is None
    assert row.attempts == 0, "a disabled sender is not a failed attempt"

    # And once it is on, the same row goes out.
    assert (await _dispatch(env, StubFcm())).delivered == 1


async def test_a_dry_run_writes_nothing_at_all(env):
    """A dry run that settles rows is not a dry run.

    Both the no-device and the has-device paths must leave the queue exactly as they found
    it, or running `--dry-run` to see what is pending silently drains it.
    """
    _reachable, with_device, _u1 = await staff(env, fcm_token="dev")
    _unreachable, without_device, _u2 = await staff(env)
    reachable_id = await queue(env, recipient_kind="merchant", recipient_id=with_device.id)
    unreachable_id = await queue(env, recipient_kind="merchant", recipient_id=without_device.id)

    report = await _dispatch(env, None)

    assert report.considered == 2
    assert report.retrying == 1
    assert report.no_devices == 1
    for notification_id in (reachable_id, unreachable_id):
        row = await _row(env, notification_id)
        assert row.delivered_at is None, "nothing may be settled"
        assert row.attempts == 0, "nothing may be counted as an attempt"
        assert row.last_error is None


async def test_a_delivered_row_is_never_sent_twice(env):
    _token, merchant, _u = await staff(env, fcm_token="dev")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    await _dispatch(env, StubFcm())

    fcm = StubFcm()
    report = await _dispatch(env, fcm)

    assert report.considered == 0
    assert fcm.sent == []


async def test_rows_are_delivered_oldest_first(env):
    _token, merchant, _u = await staff(env, fcm_token="dev")
    from tests.integration.notifications.conftest import minutes_ago

    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="Second")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="First",
                created_at=minutes_ago(30))
    fcm = StubFcm()

    await _dispatch(env, fcm)

    assert [message.title for _token, message in fcm.sent] == ["First", "Second"]
