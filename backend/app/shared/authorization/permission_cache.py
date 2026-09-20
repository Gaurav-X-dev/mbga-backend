import json
import logging
import time

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PermissionCache:
    """Best-effort cache of effective permissions.

    The cache never makes an authorization decision on its own: a miss, a disabled cache or a
    Redis failure returns None and the caller loads permissions from the database. After a
    failure, reads and writes are skipped for `failure_backoff_seconds` so an unavailable Redis
    does not slow down every request. Invalidation is always attempted.
    """

    # Shared across instances (one instance is created per request).
    _unavailable_until: float = 0.0

    def __init__(self, redis: Redis | None, ttl_seconds: int, failure_backoff_seconds: float = 30.0) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.failure_backoff_seconds = failure_backoff_seconds

    @classmethod
    def reset_availability(cls) -> None:
        cls._unavailable_until = 0.0

    CHANNELS = ("ADMIN", "MERCHANT", "DELIVERY", "CUSTOMER")

    def _key(self, user_id: str, version: int = 1, channel: str | None = None) -> str:
        # Permissions differ per app channel, so the channel is part of the key.
        suffix = f":{channel}" if channel else ""
        return f"auth:permissions:user:{user_id}{suffix}:v{version}"

    def _usable(self) -> bool:
        return self.redis is not None and time.monotonic() >= PermissionCache._unavailable_until

    def _mark_unavailable(self, action: str) -> None:
        was_available = time.monotonic() >= PermissionCache._unavailable_until
        PermissionCache._unavailable_until = time.monotonic() + self.failure_backoff_seconds
        if was_available:
            logger.warning(
                "Permission cache %s failed; using the database for %.0f seconds",
                action,
                self.failure_backoff_seconds,
                exc_info=True,
            )

    async def get(self, user_id: str, version: int = 1, channel: str | None = None) -> set[str] | None:
        if not self._usable():
            return None
        try:
            value = await self.redis.get(self._key(user_id, version, channel))
        except Exception:
            self._mark_unavailable("read")
            return None
        if not value:
            return None
        return set(json.loads(value))

    async def set(self, user_id: str, permissions: set[str], version: int = 1, channel: str | None = None) -> None:
        if not self._usable():
            return
        try:
            await self.redis.set(self._key(user_id, version, channel), json.dumps(sorted(permissions)), ex=self.ttl_seconds)
        except Exception:
            self._mark_unavailable("write")

    async def invalidate_user(self, user_id: str, version: int = 1) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.delete(self._key(user_id, version), *(self._key(user_id, version, channel) for channel in self.CHANNELS))
        except Exception:
            logger.warning("Permission cache invalidation failed", exc_info=True)
