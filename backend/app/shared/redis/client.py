from collections.abc import AsyncGenerator

from redis.asyncio import Redis, from_url

from app.config.redis import get_redis_url

_redis: Redis | None = None


def get_redis_client() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(get_redis_url(), decode_responses=True)
    return _redis


async def get_redis() -> AsyncGenerator[Redis, None]:
    yield get_redis_client()
