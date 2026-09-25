"""Delivering without waiting for the worker.

The property that matters is not that a task is spawned - it is that spawning it can never
hurt the request that spawned it. A notification is the least important thing happening in
any request that queues one, so a Firebase outage, a missing credential or a crash inside
the dispatch must all leave the caller's response exactly as it was.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.notifications import autodispatch
from app.shared.notifications.models import NotificationOutbox
from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def _event() -> NotificationEvent:
    return NotificationEvent(
        event_type="ORDER_PLACED",
        recipient_kind="customer",
        recipient_id=str(uuid4()),
        entity_type="order",
        entity_id=str(uuid4()),
        title="Order placed",
        body="Order ORD-2609-0001 has been placed.",
    )


@pytest.fixture(autouse=True)
def _clear_flag():
    """Each test starts with no request in flight."""
    autodispatch.take_queued()
    yield
    autodispatch.take_queued()


async def test_queueing_marks_the_request_so_the_middleware_can_dispatch(env):
    async with env.sessions() as session:
        NotificationOutboxWriter(session).queue(_event())
        await session.commit()

    assert autodispatch.take_queued() is True


async def test_the_flag_clears_when_it_is_read(env):
    """Two requests must not both trigger on one queued notification."""
    async with env.sessions() as session:
        NotificationOutboxWriter(session).queue(_event())
        await session.commit()

    assert autodispatch.take_queued() is True
    assert autodispatch.take_queued() is False


async def test_a_request_that_queues_nothing_triggers_nothing(env):
    assert autodispatch.take_queued() is False


async def test_scheduling_with_push_off_is_a_no_op(env, monkeypatch):
    """A deployment with no Firebase must not spawn a task on every write."""
    from app.config.app import get_settings

    settings = get_settings().model_copy(update={"fcm_enabled": False})
    monkeypatch.setattr(autodispatch, "get_settings", lambda: settings)

    autodispatch.schedule_dispatch()

    assert not autodispatch._in_flight


async def test_a_broken_credential_never_escapes_into_the_request(env, monkeypatch):
    """The response has already gone out; there is nobody left to report a failure to."""
    from app.config.app import get_settings

    settings = get_settings().model_copy(
        update={"fcm_enabled": True, "fcm_auto_dispatch": True, "fcm_credentials_file": "does/not/exist.json"}
    )
    monkeypatch.setattr(autodispatch, "get_settings", lambda: settings)

    # Raises nothing, and the row it could not send stays queued for the worker.
    await autodispatch._dispatch()


async def test_a_failed_dispatch_leaves_the_row_queued(env, monkeypatch):
    from app.config.app import get_settings

    row_id = str(uuid4())
    async with env.sessions() as session:
        session.add(
            NotificationOutbox(
                id=row_id,
                event_type="ORDER_PLACED",
                recipient_kind="customer",
                recipient_id=str(uuid4()),
                entity_type="order",
                entity_id=str(uuid4()),
                title="Order placed",
                body="body",
                severity="INFO",
                delivered_at=None,
                attempts=0,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    settings = get_settings().model_copy(
        update={"fcm_enabled": True, "fcm_auto_dispatch": True, "fcm_credentials_file": "nope.json"}
    )
    monkeypatch.setattr(autodispatch, "get_settings", lambda: settings)
    await autodispatch._dispatch()

    from sqlalchemy import select

    row = await env.scalar(select(NotificationOutbox).where(NotificationOutbox.id == row_id))
    assert row.delivered_at is None, "the worker must still be able to pick it up"
    assert row.attempts == 0, "a failed auto-dispatch is not a failed delivery attempt"
