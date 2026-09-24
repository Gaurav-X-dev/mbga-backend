from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel, SessionType
from app.modules.authentication.session_service import SessionService
from app.modules.users.role_repository import UserRoleRepository
from app.shared.authorization.context import AuthContext
from app.shared.authorization.exceptions import AuthorizationDeniedError
from app.shared.authorization.permission_cache import PermissionCache
from app.shared.authorization.permission_checker import EffectivePermissionService
from app.shared.database.session import get_db_session
from app.shared.redis.client import get_redis

bearer_scheme = HTTPBearer(auto_error=False)
FULL_SESSION_TYPES = frozenset({SessionType.ACCESS.value})
ONBOARDING_SESSION_TYPES = frozenset({SessionType.ONBOARDING.value})


async def _validated_context(
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
    session: AsyncSession,
    *,
    allowed_types: frozenset[str],
    channel: LoginChannel | None = None,
) -> AuthContext:
    validated = await SessionService(session, settings).validate_access_token(
        credentials.credentials if credentials else None,
        allowed_types=allowed_types,
        channel=channel,
    )
    return AuthContext(
        user_id=validated.user.id,
        login_channel=validated.channel,
        session_id=validated.session.id,
        token_type=validated.token_type,
    )


async def require_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> AuthContext:
    """Full app session: a live access-token session whose account may use its app.

    Onboarding (customer registration) tokens are rejected here with TOKEN_TYPE_NOT_ALLOWED.
    """
    return await _validated_context(credentials, settings, session, allowed_types=FULL_SESSION_TYPES)


async def require_onboarding_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> AuthContext:
    """Restricted customer-registration session. Only /customer/registration routes use this."""
    return await _validated_context(
        credentials,
        settings,
        session,
        allowed_types=ONBOARDING_SESSION_TYPES,
        channel=LoginChannel.CUSTOMER,
    )


def get_effective_permission_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EffectivePermissionService:
    cache = PermissionCache(
        redis,
        settings.permission_cache_ttl_seconds,
        failure_backoff_seconds=settings.redis_failure_backoff_seconds,
    )
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
            raise AuthorizationDeniedError("CHANNEL_NOT_ALLOWED")

    return dependency
