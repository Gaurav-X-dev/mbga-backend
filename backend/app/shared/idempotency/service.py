"""Reusable idempotency for retry-sensitive POSTs.

Spec §1 lists ``POST /orders``, ``POST /payments`` and ``POST /inventory/movements`` as
accepting an optional ``Idempotency-Key``. A driver on a patchy connection retries; the
retry must return the first result rather than create a second order or payment.

Never used on authentication endpoints — those have their own replay protection through
the OTP challenge and refresh-token rotation.

Flow:

1. ``begin`` inserts a PROCESSING row. The unique constraint makes that the single winner.
2. If the insert collides, the existing row decides: identical payload replays its result,
   a different payload is a 409, and a still-PROCESSING row is a 409 telling the client to
   retry shortly.
3. ``complete`` or ``fail`` records the outcome.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.idempotency.models import COMPLETED, FAILED, PROCESSING, IdempotencyKey

# How long a key is honoured. Long enough for any realistic mobile retry, short enough that
# the table stays small and a key can eventually be reused.
DEFAULT_TTL_HOURS = 24
MAX_KEY_LENGTH = 120


@dataclass(frozen=True)
class Replay:
    """A previously completed result, to be returned instead of acting again."""

    response_status: int | None
    response_body: Any | None
    result_reference: str | None


def fingerprint(payload: Any) -> str:
    """Stable SHA-256 of a request body.

    Sorted keys make the hash independent of field order, so a client that serialises its
    JSON differently on the retry still matches. The body itself is never stored.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _in_progress() -> ApiError:
    """Another request holds this key right now; the client should retry shortly."""
    return ApiError("REQUEST_IN_PROGRESS", status.HTTP_409_CONFLICT, headers={"Retry-After": "2"})


def validate_key(key: str | None, *, field: str = "Idempotency-Key") -> str | None:
    if key is None:
        return None
    cleaned = key.strip()
    if not cleaned or len(cleaned) > MAX_KEY_LENGTH:
        raise ApiError(
            "VALIDATION_ERROR",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            fields=[{"field": field, "code": "idempotency_key_invalid", "message": f"Send 1 to {MAX_KEY_LENGTH} characters."}],
        )
    return cleaned


class IdempotencyService:
    def __init__(self, session: AsyncSession, *, ttl_hours: int = DEFAULT_TTL_HOURS) -> None:
        self.session = session
        self.ttl = timedelta(hours=ttl_hours)

    async def begin(
        self,
        *,
        actor: BusinessActor,
        operation: str,
        key: str,
        payload: Any,
    ) -> tuple[IdempotencyKey | None, Replay | None]:
        """Claim the key, or hand back the earlier result.

        Returns ``(record, None)`` when this caller owns the operation and should proceed,
        or ``(None, replay)`` when a completed attempt already exists.
        """
        digest = fingerprint(payload)
        now = datetime.now(UTC)
        # Probed without a lock on purpose. `SELECT ... FOR UPDATE` on a row that does not
        # exist takes an InnoDB gap lock, and two concurrent retries then deadlock trying
        # to insert into the same gap. The unique constraint is the arbiter instead; the
        # lock is only taken once a row is known to exist.
        existing = await self._load(actor, operation, key, lock=False)
        if existing is not None:
            return None, self._resolve(await self._relock(existing), digest, now)

        record = IdempotencyKey(
            id=str(uuid4()),
            actor_user_id=actor.user_id,
            merchant_id=actor.merchant_id or "",
            operation=operation,
            idempotency_key=key,
            request_fingerprint=digest,
            status=PROCESSING,
            created_at=now,
            expires_at=now + self.ttl,
        )
        try:
            # A savepoint, so losing the race rolls back only this insert and leaves any
            # work the caller already did on the outer transaction intact.
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except (IntegrityError, OperationalError):
            # Depending on where the failure surfaced, the savepoint rollback may or may
            # not have detached the pending object. Leaving it attached would make the
            # caller's commit retry the very insert that just failed.
            if record in self.session:
                self.session.expunge(record)
            # Read without a lock: several losers all taking `FOR UPDATE` on the contended
            # row (and on the gap the winner is still inserting into) deadlock each other.
            concurrent = await self._load(actor, operation, key, lock=False)
            if concurrent is None:
                # The winner's row exists but its transaction has not committed, so this
                # session cannot read it yet. That is precisely "another request holds this
                # key right now", which is what REQUEST_IN_PROGRESS tells the client.
                raise _in_progress() from None
            return None, self._resolve(concurrent, digest, datetime.now(UTC))
        return record, None

    async def _relock(self, record: IdempotencyKey) -> IdempotencyKey:
        """Re-read an existing row under a row lock before mutating it."""
        locked = await self.session.scalar(
            select(IdempotencyKey).where(IdempotencyKey.id == record.id).with_for_update()
        )
        return locked or record

    def _resolve(self, record: IdempotencyKey, digest: str, now: datetime) -> Replay:
        if record.expires_at <= _naive(now, record.expires_at):
            # Expired: treat as never seen by clearing it, so the caller can retry cleanly.
            record.request_fingerprint = digest
            record.status = PROCESSING
            record.response_status = None
            record.response_body = None
            record.result_reference = None
            record.failure_code = None
            record.created_at = now
            record.expires_at = now + self.ttl
            return Replay(response_status=None, response_body=None, result_reference=None)
        if record.request_fingerprint != digest:
            raise ApiError("IDEMPOTENCY_KEY_REUSED", status.HTTP_409_CONFLICT)
        if record.status == PROCESSING:
            raise _in_progress()
        if record.status == FAILED:
            # The first attempt failed; let the caller try again under the same key.
            record.status = PROCESSING
            record.failure_code = None
            return Replay(response_status=None, response_body=None, result_reference=None)
        return Replay(
            response_status=record.response_status,
            response_body=json.loads(record.response_body) if record.response_body else None,
            result_reference=record.result_reference,
        )

    async def complete(
        self,
        record: IdempotencyKey,
        *,
        response_status: int,
        response_body: Any | None = None,
        result_reference: str | None = None,
    ) -> None:
        record.status = COMPLETED
        record.response_status = response_status
        record.response_body = json.dumps(response_body, default=str) if response_body is not None else None
        record.result_reference = result_reference
        record.completed_at = datetime.now(UTC)

    async def fail(self, record: IdempotencyKey, *, failure_code: str) -> None:
        record.status = FAILED
        record.failure_code = failure_code[:60]
        record.completed_at = datetime.now(UTC)

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete keys past their TTL. Called by the existing cleanup scripts."""
        from sqlalchemy import delete

        cutoff = now or datetime.now(UTC)
        result = await self.session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at <= cutoff.replace(tzinfo=None))
        )
        return result.rowcount or 0

    async def _load(
        self,
        actor: BusinessActor,
        operation: str,
        key: str,
        *,
        lock: bool,
    ) -> IdempotencyKey | None:
        statement = select(IdempotencyKey).where(
            IdempotencyKey.actor_user_id == actor.user_id,
            IdempotencyKey.merchant_id == (actor.merchant_id or ""),
            IdempotencyKey.operation == operation,
            IdempotencyKey.idempotency_key == key,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)


def _naive(now: datetime, sample: datetime) -> datetime:
    """Match the tz-awareness of a value read back from MySQL, which returns naive UTC."""
    return now.replace(tzinfo=None) if sample.tzinfo is None else now
