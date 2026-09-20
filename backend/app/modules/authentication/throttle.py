"""Database-backed request limits shared by every backend instance.

Keys (client IP, device ID, mobile number) are stored only as keyed hashes.
Counting and inserting are separate statements, so concurrent requests can slightly exceed a limit;
the limits are abuse controls, not exact quotas.
"""

import hashlib
import hmac
from datetime import timedelta
from math import ceil

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.models import AuthThrottleEvent
from app.modules.authentication.session_service import utc_naive, utc_now_naive
from app.shared.exceptions.api_error import ApiError

WINDOW = timedelta(hours=1)


class RequestThrottle:
    def __init__(self, session: AsyncSession, key_secret: str) -> None:
        self.session = session
        self.key_secret = key_secret.encode("utf-8")

    def key_hash(self, value: str) -> str:
        return hmac.new(self.key_secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    async def hit(self, bucket: str, value: str | None, limit: int, *, code: str = "RATE_LIMITED") -> None:
        """Count one request; raise 429 with Retry-After once `limit` requests happened in the window."""
        if not value:
            return
        key = self.key_hash(value)
        now = utc_now_naive()
        since = now - WINDOW
        count, oldest = (
            await self.session.execute(
                select(func.count(AuthThrottleEvent.id), func.min(AuthThrottleEvent.created_at)).where(
                    AuthThrottleEvent.bucket == bucket,
                    AuthThrottleEvent.key_hash == key,
                    AuthThrottleEvent.created_at >= since,
                )
            )
        ).one()
        if count >= limit:
            retry_after = max(1, ceil((utc_naive(oldest) + WINDOW - now).total_seconds())) if oldest else int(WINDOW.total_seconds())
            raise ApiError(code, status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": str(retry_after)})
        self.session.add(AuthThrottleEvent(bucket=bucket, key_hash=key, created_at=now))
        await self.session.flush()

    async def purge_expired(self) -> int:
        result = await self.session.execute(delete(AuthThrottleEvent).where(AuthThrottleEvent.created_at < utc_now_naive() - WINDOW))
        return result.rowcount or 0
