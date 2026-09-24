"""Login-session checks for access and onboarding tokens.

A signed token alone is not enough: every authenticated request must belong to a live session row
(not revoked, not expired, same user, same app channel, same token type) and to an account that is
still allowed to use the app. Revocation therefore takes effect on the next request.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.authentication.account_state import AccountState, AccountStateResolver
from app.modules.authentication.audit import AuthAuditor
from app.modules.authentication.constants import (
    REFRESH_TOKEN_TYPE,
    AuthEventType,
    LoginChannel,
    SessionType,
)
from app.modules.authentication.models import LoginSession
from app.modules.users.models import User
from app.shared.exceptions.api_error import ApiError

UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED
_REQUIRED_CLAIMS = ["sub", "session_id", "token_type", "login_channel", "exp"]
BLOCKED_CODES = {"ACCOUNT_BLOCKED", "MERCHANT_BLOCKED"}


def utc_naive(value: datetime | None) -> datetime | None:
    """MariaDB DATETIME columns come back naive (UTC); compare everything as naive UTC."""
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class ValidatedSession:
    claims: dict[str, Any]
    user: User
    session: LoginSession
    state: AccountState
    token_type: str
    channel: LoginChannel


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def decode(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self.settings.jwt_signing_secret,
                algorithms=[self.settings.jwt_algorithm],
                options={"require": _REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ApiError("TOKEN_EXPIRED", UNAUTHORIZED) from exc
        except jwt.InvalidTokenError as exc:
            raise ApiError("TOKEN_INVALID", UNAUTHORIZED) from exc

    async def validate_access_token(
        self,
        token: str | None,
        *,
        allowed_types: frozenset[str],
        channel: LoginChannel | None = None,
    ) -> ValidatedSession:
        if not token:
            raise ApiError("AUTH_REQUIRED", UNAUTHORIZED)
        claims = self.decode(token)
        token_type = claims.get("token_type")
        if token_type == REFRESH_TOKEN_TYPE or token_type not in {item.value for item in SessionType}:
            raise ApiError("TOKEN_TYPE_NOT_ALLOWED", UNAUTHORIZED)
        try:
            token_channel = LoginChannel(claims.get("login_channel"))
        except ValueError as exc:
            raise ApiError("TOKEN_INVALID", UNAUTHORIZED) from exc
        if channel is not None and token_channel != channel:
            raise ApiError("TOKEN_CHANNEL_MISMATCH", UNAUTHORIZED)
        if token_type not in allowed_types:
            raise ApiError("TOKEN_TYPE_NOT_ALLOWED", UNAUTHORIZED)

        login_session = await self.session.get(LoginSession, claims["session_id"])
        if login_session is None or login_session.user_id != claims["sub"]:
            raise ApiError("SESSION_REVOKED", UNAUTHORIZED)
        if login_session.login_channel is not None and login_session.login_channel != token_channel.value:
            raise ApiError("SESSION_REVOKED", UNAUTHORIZED)
        if login_session.session_type is not None and login_session.session_type != token_type:
            raise ApiError("SESSION_REVOKED", UNAUTHORIZED)
        user = await self.session.get(User, login_session.user_id)
        if user is None:
            raise ApiError("SESSION_REVOKED", UNAUTHORIZED)

        state = await AccountStateResolver(self.session).resolve(user, token_channel)
        # Account problems are reported before revocation so the app can show the reason
        # (sessions of blocked accounts are usually revoked as well).
        denial = state.onboarding_denial if token_type == SessionType.ONBOARDING else state.denial
        if denial is not None:
            if denial[0] in BLOCKED_CODES:
                await AuthAuditor(self.session, store_ip=False).record(
                    AuthEventType.BLOCKED_ACCOUNT_ACCESS,
                    channel=token_channel,
                    success=False,
                    user_id=user.id,
                    reason=denial[0],
                    entity_id=login_session.id,
                )
                await self.session.commit()
            raise ApiError(denial[0], denial[1])
        if login_session.revoked_at is not None:
            raise ApiError("SESSION_REVOKED", UNAUTHORIZED)
        expires_at = utc_naive(login_session.expires_at)
        if expires_at is not None and expires_at <= utc_now_naive():
            raise ApiError("SESSION_EXPIRED", UNAUTHORIZED)
        return ValidatedSession(claims=claims, user=user, session=login_session, state=state, token_type=token_type, channel=token_channel)

    async def revoke(self, login_session: LoginSession, reason: str) -> None:
        if login_session.revoked_at is None:
            login_session.revoked_at = datetime.now(UTC)
            login_session.revoked_reason = reason
        login_session.push_token = None

    async def revoke_all_for_user(self, user_id: str, reason: str) -> int:
        result = await self.session.execute(
            update(LoginSession)
            .where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason, push_token=None)
        )
        return result.rowcount or 0
