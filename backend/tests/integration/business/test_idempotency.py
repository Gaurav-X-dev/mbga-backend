"""Phase B: idempotency for retry-sensitive business operations."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.modules.authentication.constants import LoginChannel
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.idempotency import (
    IdempotencyKey,
    IdempotencyService,
    fingerprint,
    validate_key,
)
from app.shared.idempotency.models import PROCESSING

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ORDER = "orders.create"

PAYLOAD = {"items": [{"cylinder_type": "LPG_19KG", "quantity": 4}], "delivery_site_id": None}
@pytest.fixture
def key() -> str:
    """A key unique to this test run.

    Idempotency rows outlive a test by design (they exist to survive retries), so reusing
    a literal key would make one run collide with the last.
    """
    return f"k-{uuid4().hex[:12]}"


def _actor(user_id: str = "u-1", merchant_id: str | None = "m-1") -> BusinessActor:
    return BusinessActor(
        user_id=user_id,
        login_channel=LoginChannel.MERCHANT if merchant_id else LoginChannel.CUSTOMER,
        display_name="Staff",
        merchant_id=merchant_id,
    )


async def test_the_first_request_claims_the_key(env, key: str) -> None:
    async with env.sessions() as db:
        record, replay = await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    assert replay is None
    assert record.status == PROCESSING


async def test_a_retry_with_the_same_payload_replays_the_first_result(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        record, _ = await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await service.complete(record, response_status=201, response_body={"order_id": "ORD-1"}, result_reference="ORD-1")
        await db.commit()

    async with env.sessions() as db:
        record, replay = await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    assert record is None
    assert replay.response_status == 201
    assert replay.response_body == {"order_id": "ORD-1"}
    assert replay.result_reference == "ORD-1"


async def test_only_one_row_exists_after_a_retry(env, key: str) -> None:
    """The domain side effect happens once; the retry never reaches the handler."""
    async with env.sessions() as db:
        service = IdempotencyService(db)
        record, _ = await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await service.complete(record, response_status=201, response_body={"order_id": "ORD-2"})
        await db.commit()
    async with env.sessions() as db:
        await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    rows = await env.scalar(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key).with_only_columns(IdempotencyKey.id)
    )
    assert rows is not None
    count = (await env.execute(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key))).all()
    assert len(count) == 1


async def test_the_same_key_with_a_different_payload_is_a_conflict(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        record, _ = await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await service.complete(record, response_status=201, response_body={"order_id": "ORD-3"})
        await db.commit()

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await IdempotencyService(db).begin(
                actor=_actor(), operation=ORDER, key=key, payload={"items": [{"quantity": 99}]}
            )

    assert (error.value.status_code, error.value.code) == (409, "IDEMPOTENCY_KEY_REUSED")


async def test_a_request_still_in_flight_is_a_conflict_with_retry_after(env, key: str) -> None:
    async with env.sessions() as db:
        await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)

    assert (error.value.status_code, error.value.code) == (409, "REQUEST_IN_PROGRESS")
    assert error.value.headers["Retry-After"] == "2"


async def test_two_different_actors_may_use_the_same_key(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        first, _ = await service.begin(actor=_actor("u-a"), operation=ORDER, key=key, payload=PAYLOAD)
        second, replay = await service.begin(actor=_actor("u-b"), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    assert replay is None
    assert first.id != second.id


async def test_two_merchants_do_not_collide_on_the_same_key(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        first, _ = await service.begin(actor=_actor("u-a", "m-1"), operation=ORDER, key=key, payload=PAYLOAD)
        second, replay = await service.begin(actor=_actor("u-a", "m-2"), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    assert replay is None
    assert first.merchant_id == "m-1" and second.merchant_id == "m-2"


async def test_a_customer_actor_with_no_merchant_is_scoped_by_empty_string(env, key: str) -> None:
    """MySQL treats NULLs as distinct, so the scope column must never be NULL."""
    async with env.sessions() as db:
        record, _ = await IdempotencyService(db).begin(
            actor=_actor("u-cust", merchant_id=None), operation=ORDER, key=key, payload=PAYLOAD
        )
        await db.commit()

    assert record.merchant_id == ""

    async with env.sessions() as db:
        with pytest.raises(ApiError):
            await IdempotencyService(db).begin(
                actor=_actor("u-cust", merchant_id=None), operation=ORDER, key=key, payload={"other": True}
            )


async def test_the_same_key_on_a_different_operation_is_independent(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        _, replay = await service.begin(actor=_actor(), operation="payments.record", key=key, payload=PAYLOAD)
        await db.commit()

    assert replay is None


async def test_a_failed_attempt_may_be_retried_under_the_same_key(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        record, _ = await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await service.fail(record, failure_code="STOCK_INSUFFICIENT")
        await db.commit()

    async with env.sessions() as db:
        record, replay = await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()

    assert replay is not None
    assert replay.response_status is None  # nothing to replay; the caller acts again


async def test_an_expired_key_can_be_claimed_again(env, key: str) -> None:
    async with env.sessions() as db:
        service = IdempotencyService(db)
        record, _ = await service.begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await service.complete(record, response_status=201, response_body={"order_id": "old"})
        await db.commit()

    await env.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.idempotency_key == key)
        .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
    )

    async with env.sessions() as db:
        _, replay = await IdempotencyService(db).begin(
            actor=_actor(), operation=ORDER, key=key, payload={"items": [{"quantity": 1}]}
        )
        await db.commit()

    # Expired, so a different payload is accepted rather than reported as reuse.
    assert replay.response_status is None


async def test_expired_keys_are_purged(env, key: str) -> None:
    async with env.sessions() as db:
        await IdempotencyService(db).begin(actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD)
        await db.commit()
    await env.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.idempotency_key == key)
        .values(expires_at=datetime.now(UTC) - timedelta(days=2))
    )

    async with env.sessions() as db:
        removed = await IdempotencyService(db).purge_expired()
        await db.commit()

    assert removed >= 1
    assert await env.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)) is None


async def test_concurrent_identical_requests_produce_one_claim(env, key: str) -> None:
    """Two retries racing: the unique constraint lets exactly one through."""

    async def attempt() -> bool:
        async with env.sessions() as db:
            try:
                record, _ = await IdempotencyService(db).begin(
                    actor=_actor(), operation=ORDER, key=key, payload=PAYLOAD
                )
                await db.commit()
                return record is not None
            except ApiError:
                return False

    results = await asyncio.gather(*(attempt() for _ in range(4)))

    assert sum(results) == 1
    rows = (await env.execute(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key))).all()
    assert len(rows) == 1


def test_the_fingerprint_ignores_key_order() -> None:
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_different_payloads_fingerprint_differently() -> None:
    assert fingerprint({"quantity": 4}) != fingerprint({"quantity": 5})


def test_the_fingerprint_does_not_contain_the_payload() -> None:
    """Nothing sensitive reaches the table: only a 64-character digest is stored."""
    digest = fingerprint({"otp": "4024", "aadhaar": "123456789012"})
    assert len(digest) == 64
    assert "4024" not in digest and "123456789012" not in digest


@pytest.mark.parametrize("bad", ["", "   ", "x" * 121])
def test_an_unusable_key_header_is_rejected(bad: str) -> None:
    with pytest.raises(ApiError) as error:
        validate_key(bad)
    assert error.value.status_code == 422


def test_a_missing_key_header_is_allowed() -> None:
    assert validate_key(None) is None
    assert validate_key(" k-9 ") == "k-9"
