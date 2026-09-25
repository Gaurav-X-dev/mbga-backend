from collections.abc import AsyncGenerator

from app.config.app import get_settings
from redis.asyncio import Redis, from_url

_redis: Redis | None = None


def get_redis_client() -> Redis | None:
    """Shared Redis client, or None when Redis is disabled for local development.

    Short socket timeouts keep an unreachable Redis from delaying requests: on Windows a
    refused local connection otherwise takes about two seconds per call.
    """
    global _redis
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    if _redis is None:
        _redis = from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            retry_on_timeout=False,
        )
    return _redis


async def get_redis() -> AsyncGenerator[Redis | None, None]:
    yield get_redis_client()
