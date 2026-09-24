"""`purge_expired()` must be invisible to the limits it cleans up after.

The cleanup script runs against production data, so the property that matters is not "it
deletes rows" but "deleting them changes no answer the limiter would have given". These
tests pin that: a counter that is mid-window survives a purge untouched, and a counter whose
rows have aged out was already back to zero before the purge ever ran.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.authentication.models import AuthThrottleEvent
from app.modules.authentication.session_service import utc_now_naive
from app.modules.authentication.throttle import WINDOW, RequestThrottle
from app.shared.exceptions.api_error import ApiError

# `env` and its database fixtures come from this package's conftest, like every other test
# file here - importing them would shadow the fixture rather than register it.
pytestmark = [pytest.mark.integration, pytest.mark.mysql]

SECRET = "cleanup-test-secret"


@pytest.fixture
def bucket() -> str:
    """A bucket of this test's own.

    The integration database is prepared once per session, not per test, so a shared bucket
    name would let one test count another's rows.
    """
    return f"test_bucket_{uuid4().hex[:8]}:ip"


async def _count(session, bucket: str) -> int:
    return await session.scalar(
        select(func.count()).select_from(AuthThrottleEvent).where(AuthThrottleEvent.bucket == bucket)
    ) or 0


async def _age(session, throttle: RequestThrottle, bucket: str, value: str, *, older_than: timedelta) -> None:
    """Backdate this key's rows so they fall outside the window."""
    rows = await session.scalars(
        select(AuthThrottleEvent).where(
            AuthThrottleEvent.bucket == bucket, AuthThrottleEvent.key_hash == throttle.key_hash(value)
        )
    )
    for row in rows:
        row.created_at = utc_now_naive() - older_than
    await session.commit()


async def test_a_purge_leaves_an_in_window_counter_exactly_where_it_was(env, bucket):
    """The property the cleanup script depends on: recent counts are untouched."""
    async with env.sessions() as session:
        throttle = RequestThrottle(session, SECRET)
        for _ in range(3):
            await throttle.hit(bucket, "10.0.0.1", limit=5)
        await session.commit()

        removed = await throttle.purge_expired()
        await session.commit()

        # The fourth and fifth hits still pass, the sixth is still refused - the same
        # answers the limiter would have given had the purge never run.
        for _ in range(2):
            await throttle.hit(bucket, "10.0.0.1", limit=5)
        await session.commit()
        with pytest.raises(ApiError) as refused:
            await throttle.hit(bucket, "10.0.0.1", limit=5)

    assert refused.value.status_code == 429
    assert removed == 0, "nothing was old enough to purge"


async def test_rows_outside_the_window_are_already_ignored_before_any_purge(env, bucket):
    """Why deleting them is a no-op: the limiter had stopped counting them anyway."""
    async with env.sessions() as session:
        throttle = RequestThrottle(session, SECRET)
        for _ in range(5):
            await throttle.hit(bucket, "10.0.0.2", limit=5)
        await session.commit()

        # At the limit: the next hit is refused.
        with pytest.raises(ApiError):
            await throttle.hit(bucket, "10.0.0.2", limit=5)

        await _age(session, throttle, bucket, "10.0.0.2", older_than=WINDOW + timedelta(minutes=5))

        # The rows are still on the table, and the caller is already allowed through.
        assert await _count(session, bucket) >= 5
        await throttle.hit(bucket, "10.0.0.2", limit=5)
        await session.commit()


async def test_a_purge_removes_the_aged_rows_and_only_those(env, bucket):
    async with env.sessions() as session:
        throttle = RequestThrottle(session, SECRET)
        await throttle.hit(bucket, "10.0.0.3", limit=10)
        await throttle.hit(bucket, "10.0.0.4", limit=10)
        await session.commit()
        await _age(session, throttle, bucket, "10.0.0.3", older_than=WINDOW + timedelta(minutes=1))

        before = await _count(session, bucket)
        removed = await throttle.purge_expired()
        await session.commit()
        after = await _count(session, bucket)

    assert before == 2
    assert removed >= 1
    # The fresh row survived; only the aged one went.
    assert after == 1


async def test_purging_an_empty_window_is_harmless(env, bucket):
    """The script runs daily whether or not there is anything to do."""
    async with env.sessions() as session:
        throttle = RequestThrottle(session, SECRET)
        await throttle.hit(bucket, "10.0.0.5", limit=10)
        await session.commit()

        first = await throttle.purge_expired()
        second = await throttle.purge_expired()
        await session.commit()

        assert first == 0
        assert second == 0
        assert await _count(session, bucket) == 1
