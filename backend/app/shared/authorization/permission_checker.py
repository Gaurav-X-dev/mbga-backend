from datetime import UTC, datetime
from typing import Protocol

from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.context import AuthContext
from app.shared.authorization.exceptions import AuthorizationDeniedError
from app.shared.authorization.permission_cache import PermissionCache


class PermissionRepositoryProtocol(Protocol):
    async def get_effective_permissions(
        self,
        *,
        user_id: str,
        login_channel: LoginChannel,
        now: datetime,
    ) -> set[str]:
        ...


class EffectivePermissionService:
    def __init__(
        self,
        repository: PermissionRepositoryProtocol,
        cache: PermissionCache | None = None,
    ) -> None:
        self.repository = repository
        self.cache = cache

    async def get_effective_permissions(self, context: AuthContext) -> set[str]:
        if self.cache:
            cached = await self.cache.get(context.user_id)
            if cached is not None:
                return cached
        permissions = await self.repository.get_effective_permissions(
            user_id=context.user_id,
            login_channel=context.login_channel,
            now=datetime.now(UTC),
        )
        if self.cache:
            await self.cache.set(context.user_id, permissions)
        return permissions

    async def has_permission(self, context: AuthContext, permission: str) -> bool:
        permissions = await self.get_effective_permissions(context)
        return permission in permissions

    async def require_permission(self, context: AuthContext, permission: str) -> None:
        if not await self.has_permission(context, permission):
            raise AuthorizationDeniedError()

    async def require_any_permission(self, context: AuthContext, required: tuple[str, ...]) -> None:
        permissions = await self.get_effective_permissions(context)
        if not any(permission in permissions for permission in required):
            raise AuthorizationDeniedError()

    async def require_all_permissions(self, context: AuthContext, required: tuple[str, ...]) -> None:
        permissions = await self.get_effective_permissions(context)
        if not all(permission in permissions for permission in required):
            raise AuthorizationDeniedError()
