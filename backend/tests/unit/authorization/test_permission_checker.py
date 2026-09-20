from datetime import UTC, datetime

import pytest

from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.context import AuthContext
from app.shared.authorization.exceptions import AuthorizationDeniedError
from app.shared.authorization.permission_checker import EffectivePermissionService

pytestmark = pytest.mark.unit


class FakePermissionRepository:
    def __init__(self, permissions: set[str]) -> None:
        self.permissions = permissions
        self.calls = 0

    async def get_effective_permissions(self, *, user_id: str, login_channel: LoginChannel, now: datetime) -> set[str]:
        self.calls += 1
        return self.permissions


class FakePermissionCache:
    def __init__(self, permissions: set[str] | None = None) -> None:
        self.permissions = permissions
        self.invalidated: list[str] = []

    async def get(self, user_id: str, version: int = 1, channel: str | None = None) -> set[str] | None:
        return self.permissions

    async def set(self, user_id: str, permissions: set[str], version: int = 1, channel: str | None = None) -> None:
        self.permissions = permissions

    async def invalidate_user(self, user_id: str, version: int = 1) -> None:
        self.invalidated.append(user_id)
        self.permissions = None


@pytest.mark.asyncio
async def test_effective_permissions_use_repository_when_cache_misses() -> None:
    repo = FakePermissionRepository({"orders.view"})
    cache = FakePermissionCache()
    service = EffectivePermissionService(repo, cache)

    permissions = await service.get_effective_permissions(AuthContext("u1", LoginChannel.MERCHANT))

    assert permissions == {"orders.view"}
    assert repo.calls == 1
    assert cache.permissions == {"orders.view"}


@pytest.mark.asyncio
async def test_missing_permission_denied() -> None:
    service = EffectivePermissionService(FakePermissionRepository({"orders.view"}))

    with pytest.raises(AuthorizationDeniedError):
        await service.require_permission(AuthContext("u1", LoginChannel.MERCHANT), "payments.reconcile")


@pytest.mark.asyncio
async def test_any_permission_logic() -> None:
    service = EffectivePermissionService(FakePermissionRepository({"orders.view"}))

    await service.require_any_permission(
        AuthContext("u1", LoginChannel.MERCHANT),
        ("payments.reconcile", "orders.view"),
    )


@pytest.mark.asyncio
async def test_all_permission_logic_denies_when_one_missing() -> None:
    service = EffectivePermissionService(FakePermissionRepository({"orders.view"}))

    with pytest.raises(AuthorizationDeniedError):
        await service.require_all_permissions(
            AuthContext("u1", LoginChannel.MERCHANT),
            ("orders.view", "payments.reconcile"),
        )


@pytest.mark.asyncio
async def test_permission_cache_invalidation() -> None:
    cache = FakePermissionCache({"orders.view"})

    await cache.invalidate_user("u1")

    assert cache.invalidated == ["u1"]
    assert cache.permissions is None
