import secrets

import pytest
from pydantic import ValidationError

from app.config.app import Settings
from app.shared.authorization.permission_cache import PermissionCache

pytestmark = pytest.mark.unit


class FailingRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, *_args, **_kwargs):
        self.calls += 1
        raise ConnectionError("redis down")

    async def set(self, *_args, **_kwargs):
        self.calls += 1
        raise ConnectionError("redis down")

    async def delete(self, *_args, **_kwargs):
        self.calls += 1
        raise ConnectionError("redis down")


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttl[key] = ex

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


@pytest.fixture(autouse=True)
def reset_cache_state():
    PermissionCache.reset_availability()
    yield
    PermissionCache.reset_availability()


async def test_disabled_cache_never_returns_permissions() -> None:
    cache = PermissionCache(None, ttl_seconds=300)

    assert await cache.get("user-1") is None
    await cache.set("user-1", {"users.view"})
    await cache.invalidate_user("user-1")
    assert await cache.get("user-1") is None


async def test_cache_entries_are_separate_per_app_channel() -> None:
    redis = MemoryRedis()
    cache = PermissionCache(redis, ttl_seconds=300)

    await cache.set("user-1", {"users.view"}, channel="ADMIN")

    assert await cache.get("user-1", channel="ADMIN") == {"users.view"}
    assert await cache.get("user-1", channel="MERCHANT") is None
    await cache.invalidate_user("user-1")
    assert await cache.get("user-1", channel="ADMIN") is None


async def test_failure_falls_back_and_skips_redis_during_backoff() -> None:
    redis = FailingRedis()
    cache = PermissionCache(redis, ttl_seconds=300, failure_backoff_seconds=60)

    assert await cache.get("user-1") is None
    assert redis.calls == 1

    # Later requests use the database immediately instead of waiting on Redis again.
    second = PermissionCache(redis, ttl_seconds=300, failure_backoff_seconds=60)
    assert await second.get("user-1") is None
    await second.set("user-1", {"users.view"})
    assert redis.calls == 1


async def test_invalidation_is_attempted_even_during_backoff() -> None:
    redis = FailingRedis()
    cache = PermissionCache(redis, ttl_seconds=300, failure_backoff_seconds=60)
    await cache.get("user-1")

    await cache.invalidate_user("user-1")

    assert redis.calls == 2


async def test_zero_backoff_retries_redis_on_the_next_request() -> None:
    redis = FailingRedis()
    cache = PermissionCache(redis, ttl_seconds=300, failure_backoff_seconds=0)

    await cache.get("user-1")
    await cache.get("user-1")

    assert redis.calls == 2


async def test_working_cache_round_trip_uses_ttl() -> None:
    redis = MemoryRedis()
    cache = PermissionCache(redis, ttl_seconds=300)

    await cache.set("user-1", {"users.view", "roles.view"})

    assert await cache.get("user-1") == {"users.view", "roles.view"}
    assert list(redis.ttl.values()) == [300]
    await cache.invalidate_user("user-1")
    assert await cache.get("user-1") is None


async def test_cache_entries_are_separate_per_app_channel() -> None:
    redis = MemoryRedis()
    cache = PermissionCache(redis, ttl_seconds=300)

    await cache.set("user-1", {"users.view"}, channel="ADMIN")

    assert await cache.get("user-1", channel="ADMIN") == {"users.view"}
    assert await cache.get("user-1", channel="MERCHANT") is None
    await cache.invalidate_user("user-1")
    assert await cache.get("user-1", channel="ADMIN") is None


@pytest.mark.parametrize("env", ["local", "development", "dev", "test"])
def test_redis_can_be_disabled_for_local_environments(env: str) -> None:
    settings = Settings(_env_file=None, app_env=env, redis_enabled=False)

    assert settings.redis_enabled is False


@pytest.mark.parametrize("env", ["production", "staging", "prod"])
def test_redis_cannot_be_disabled_outside_local_environments(env: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=env, redis_enabled=False)


def test_redis_client_is_not_created_when_disabled(monkeypatch) -> None:
    from app.shared.redis import client as redis_client

    monkeypatch.setattr(
        redis_client,
        "get_settings",
        lambda: Settings(_env_file=None, app_env="local", redis_enabled=False),
    )
    monkeypatch.setattr(redis_client, "_redis", None)

    assert redis_client.get_redis_client() is None


def test_redis_client_uses_short_timeouts(monkeypatch) -> None:
    from app.shared.redis import client as redis_client

    monkeypatch.setattr(
        redis_client,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            app_env="production",
            jwt_signing_secret=secrets.token_urlsafe(48),
            sms_provider="sms",
            redis_url="redis://127.0.0.1:6399/0",
            redis_socket_connect_timeout_seconds=0.25,
        ),
    )
    monkeypatch.setattr(redis_client, "_redis", None)

    client = redis_client.get_redis_client()

    assert client is not None
    assert client.connection_pool.connection_kwargs["socket_connect_timeout"] == 0.25
    monkeypatch.setattr(redis_client, "_redis", None)
