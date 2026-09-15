from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.users.role_repository import UserRoleRepository
from app.shared.authorization.context import AuthContext
from app.shared.authorization.exceptions import UnauthenticatedError
from app.shared.authorization.permission_cache import PermissionCache
from app.shared.authorization.permission_checker import EffectivePermissionService
from app.shared.database.session import get_db_session
from app.shared.redis.client import get_redis

bearer_scheme = HTTPBearer(auto_error=False)

async def require_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> AuthContext:
    if credentials is None:
        raise UnauthenticatedError()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_signing_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("token_type") not in {"access", "onboarding"}:
            raise ValueError("not an access token")
        channel = LoginChannel(payload.get("login_channel"))
        return AuthContext(
            user_id=payload["sub"],
            login_channel=channel,
            session_id=payload.get("session_id"),
        )
    except Exception as exc:
        raise UnauthenticatedError() from exc


def get_effective_permission_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EffectivePermissionService:
    cache = PermissionCache(redis, settings.permission_cache_ttl_seconds)
    return EffectivePermissionService(UserRoleRepository(session), cache)


def require_permission(permission: str) -> Callable:
    async def dependency(
        context: Annotated[AuthContext, Depends(require_authenticated_user)],
        service: Annotated[EffectivePermissionService, Depends(get_effective_permission_service)],
    ) -> None:
        await service.require_permission(context, permission)

    return dependency


def require_any_permission(*permissions: str) -> Callable:
    async def dependency(
        context: Annotated[AuthContext, Depends(require_authenticated_user)],
        service: Annotated[EffectivePermissionService, Depends(get_effective_permission_service)],
    ) -> None:
        await service.require_any_permission(context, permissions)

    return dependency


def require_all_permissions(*permissions: str) -> Callable:
    async def dependency(
        context: Annotated[AuthContext, Depends(require_authenticated_user)],
        service: Annotated[EffectivePermissionService, Depends(get_effective_permission_service)],
    ) -> None:
        await service.require_all_permissions(context, permissions)

    return dependency


def require_role(role_code: str) -> Callable:
    return require_permission(f"roles.{role_code}")


def require_login_channel(login_channel: LoginChannel) -> Callable:
    async def dependency(context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> None:
        if context.login_channel != login_channel:
            from app.shared.authorization.exceptions import AuthorizationDeniedError

            raise AuthorizationDeniedError()

    return dependency
