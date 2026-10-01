"""Head-office view of who is signed in, and the ability to end a session.

The merchant and delivery apps each manage their own sessions; this is the admin channel's
read-across-everything view, used by the Login Sessions screen in the web panel. Listing is
separate from revoking so that a support user can be allowed to look without being allowed
to sign people out.

Sessions are never deleted: a revoked row keeps its history, which is what makes
"who was signed in when" answerable after the fact.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.models import LoginSession
from app.modules.authentication.session_service import utc_now_naive
from app.modules.users.models import User
from app.shared.authorization.dependencies import require_permission
from app.shared.business.pagination import Page, page_params
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/auth/sessions", tags=["admin-login-sessions"])

VIEW = Depends(require_permission("authentication.view_sessions"))
REVOKE = Depends(require_permission("authentication.revoke_sessions"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

SessionStatus = Literal["ACTIVE", "EXPIRED", "REVOKED"]


class LoginSessionItem(BaseModel):
    id: str
    user_id: str
    user_name: str | None
    user_mobile: str | None
    user_role: str | None
    login_channel: str | None
    status: SessionStatus
    device_name: str | None
    device_type: str | None
    user_agent: str | None
    app_version: str | None
    ip_address: str | None
    created_at: datetime | None
    last_activity_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None


class LoginSessionListResponse(BaseModel):
    items: list[LoginSessionItem]
    total: int
    limit: int
    offset: int


class LoginSessionStats(BaseModel):
    active: int
    expired: int
    revoked: int
    """Sessions that ended in the last 24 hours, however they ended."""
    ended_last_24h: int


def _status_of(row: LoginSession, now: datetime) -> SessionStatus:
    if row.revoked_at is not None:
        return "REVOKED"
    if row.expires_at is not None and row.expires_at <= now:
        return "EXPIRED"
    return "ACTIVE"


def _apply_status_filter(statement: Select, value: str, now: datetime) -> Select:
    """Status is derived from two columns, so it is filtered in SQL rather than in Python."""
    if value == "REVOKED":
        return statement.where(LoginSession.revoked_at.is_not(None))
    if value == "EXPIRED":
        return statement.where(
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at.is_not(None),
            LoginSession.expires_at <= now,
        )
    return statement.where(
        LoginSession.revoked_at.is_(None),
        or_(LoginSession.expires_at.is_(None), LoginSession.expires_at > now),
    )


@router.get(
    "",
    response_model=LoginSessionListResponse,
    dependencies=[VIEW],
    responses=error_responses(401, 403, 422),
    summary="List login sessions",
)
async def list_sessions(
    session: SessionDep,
    page: Annotated[Page, Depends(page_params)],
    status_filter: Annotated[
        str | None, Query(alias="status", description="ACTIVE, EXPIRED or REVOKED. Omit for all.")
    ] = None,
    login_channel: Annotated[str | None, Query(description="ADMIN, MERCHANT, CUSTOMER or DELIVERY.")] = None,
    user_id: Annotated[str | None, Query(description="Only this user's sessions.")] = None,
    search: Annotated[str | None, Query(description="Matches name, mobile, IP address or device.")] = None,
) -> LoginSessionListResponse:
    now = utc_now_naive()
    # Joined so one query answers "who is this", and so search can span both tables.
    statement: Select = select(LoginSession, User).join(User, User.id == LoginSession.user_id, isouter=True)

    if status_filter:
        value = status_filter.strip().upper()
        if value not in ("ACTIVE", "EXPIRED", "REVOKED"):
            raise ApiError(
                "VALIDATION_ERROR",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[{"field": "status", "code": "invalid", "message": "Use ACTIVE, EXPIRED or REVOKED."}],
            )
        statement = _apply_status_filter(statement, value, now)
    if login_channel:
        statement = statement.where(LoginSession.login_channel == login_channel.strip().upper())
    if user_id:
        statement = statement.where(LoginSession.user_id == user_id)
    if search:
        like = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                User.full_name.ilike(like),
                User.mobile_number.ilike(like),
                User.email.ilike(like),
                LoginSession.ip_address.ilike(like),
                LoginSession.device_name.ilike(like),
                LoginSession.user_agent.ilike(like),
            )
        )

    # Most recent activity first: the reason to open this screen is "who is on right now".
    statement = statement.order_by(
        func.coalesce(LoginSession.last_activity_at, LoginSession.created_at).desc(), LoginSession.id
    )
    total = int(await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)
    rows = (await session.execute(statement.limit(page.limit).offset(page.offset))).all()

    items = [
        LoginSessionItem(
            id=row.LoginSession.id,
            user_id=row.LoginSession.user_id,
            user_name=row.User.full_name if row.User else None,
            user_mobile=row.User.mobile_number if row.User else None,
            user_role=row.User.role if row.User else None,
            login_channel=row.LoginSession.login_channel,
            status=_status_of(row.LoginSession, now),
            device_name=row.LoginSession.device_name,
            device_type=row.LoginSession.device_type,
            user_agent=row.LoginSession.user_agent,
            app_version=row.LoginSession.app_version,
            ip_address=row.LoginSession.ip_address,
            created_at=row.LoginSession.created_at,
            last_activity_at=row.LoginSession.last_activity_at,
            expires_at=row.LoginSession.expires_at,
            revoked_at=row.LoginSession.revoked_at,
            revoked_reason=row.LoginSession.revoked_reason,
        )
        for row in rows
    ]
    return LoginSessionListResponse(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/stats",
    response_model=LoginSessionStats,
    dependencies=[VIEW],
    responses=error_responses(401, 403),
    summary="Login session counts",
)
async def session_stats(session: SessionDep) -> LoginSessionStats:
    now = utc_now_naive()

    async def count(statement: Select) -> int:
        return int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)

    base: Select = select(LoginSession.id)
    return LoginSessionStats(
        active=await count(_apply_status_filter(base, "ACTIVE", now)),
        expired=await count(_apply_status_filter(base, "EXPIRED", now)),
        revoked=await count(_apply_status_filter(base, "REVOKED", now)),
        ended_last_24h=await count(
            base.where(
                or_(
                    LoginSession.revoked_at > now - timedelta(hours=24),
                    LoginSession.expires_at.between(now - timedelta(hours=24), now),
                )
            )
        ),
    )


@router.post(
    "/{session_id}/revoke",
    response_model=LoginSessionItem,
    dependencies=[REVOKE],
    responses=error_responses(401, 403, 404),
    summary="Revoke a login session",
)
async def revoke_session(session_id: str, session: SessionDep) -> LoginSessionItem:
    """Ends one session. Already-ended sessions are returned unchanged rather than erroring,
    so two reviewers clicking the same row do not see a spurious failure."""
    row = await session.get(LoginSession, session_id)
    if row is None:
        raise ApiError("SESSION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    now = utc_now_naive()
    if row.revoked_at is None:
        row.revoked_at = now
        row.revoked_reason = "ADMIN_REVOKED"
        # The device must not keep receiving pushes for a session it no longer holds.
        row.push_token = None
        await session.commit()
        await session.refresh(row)
    user = await session.get(User, row.user_id)
    return LoginSessionItem(
        id=row.id,
        user_id=row.user_id,
        user_name=user.full_name if user else None,
        user_mobile=user.mobile_number if user else None,
        user_role=user.role if user else None,
        login_channel=row.login_channel,
        status=_status_of(row, now),
        device_name=row.device_name,
        device_type=row.device_type,
        user_agent=row.user_agent,
        app_version=row.app_version,
        ip_address=row.ip_address,
        created_at=row.created_at,
        last_activity_at=row.last_activity_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        revoked_reason=row.revoked_reason,
    )
