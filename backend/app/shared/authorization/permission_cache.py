import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PermissionCache:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def _key(self, user_id: str, version: int = 1) -> str:
        return f"auth:permissions:user:{user_id}:v{version}"

    async def get(self, user_id: str, version: int = 1) -> set[str] | None:
        try:
            value = await self.redis.get(self._key(user_id, version))
        except Exception:
            logger.warning("Permission cache read failed", exc_info=True)
            return None
        if not value:
            return None
        return set(json.loads(value))

    async def set(self, user_id: str, permissions: set[str], version: int = 1) -> None:
        try:
            await self.redis.setex(self._key(user_id, version), self.ttl_seconds, json.dumps(sorted(permissions)))
        except Exception:
            logger.warning("Permission cache write failed", exc_info=True)

    async def invalidate_user(self, user_id: str, version: int = 1) -> None:
        try:
            await self.redis.delete(self._key(user_id, version))
        except Exception:
            logger.warning("Permission cache invalidation failed", exc_info=True)
