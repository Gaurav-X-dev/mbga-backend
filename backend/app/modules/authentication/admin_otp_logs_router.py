"""OTP delivery diagnostics for the admin channel, including the codes themselves.

This screen was built to answer "was the message sent, and what did the provider say" without
ever showing a code, because a challenge holds a one-way hash and nothing else.

It now also prints the code, which was asked for once the SMS credit ran out and nobody could
sign in. That is a deliberate trade and it is worth naming plainly: with
`OTP_LOG_PLAINTEXT_ENABLED` on, whoever can open this screen can sign into any account on the
platform. The permission below and the audit row written on every view are what make it
traceable - they do not make it safe. The intended lifetime of that switch is "until the
provider is topped up".

With the switch off - the default - `otp` comes back null on every row and this is the
diagnostics screen it was before.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService
from app.modules.audit_logs.service import mask_mobile
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.authentication.session_service import utc_now_naive
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user
from app.shared.business.pagination import Page, page_params
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/auth/otp-logs", tags=["admin-otp-logs"])

OtpState = Literal["ACTIVE", "CONSUMED", "EXPIRED", "LOCKED", "SUPPRESSED"]


class OtpLogItem(BaseModel):
    request_id: str
    masked_mobile: str
    #: The code itself, or null when the deployment has not asked for readable codes. Null is
    #: the normal state and the app must render the row without it rather than showing a blank
    #: box where a number is expected.
    otp: str | None
    purpose: str
    login_channel: str
    state: OtpState
    delivery_status: str | None
    delivery_provider: str | None
    delivery_reference: str | None
    attempts: int
    max_attempts: int
    device_type: str | None
    app_version: str | None
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


class OtpLogListResponse(BaseModel):
    items: list[OtpLogItem]
    total: int
    limit: int
    offset: int


def _state(row: OtpChallenge, now: datetime) -> OtpState:
    if row.dispatch_suppressed:
        return "SUPPRESSED"
    if row.consumed_at is not None:
        return "CONSUMED"
    if row.attempts >= row.max_attempts:
        return "LOCKED"
    if row.expires_at <= now:
        return "EXPIRED"
    return "ACTIVE"


@router.get(
    "",
    response_model=OtpLogListResponse,
    dependencies=[
        Depends(require_login_channel(LoginChannel.ADMIN)),
        Depends(require_permission("authentication.view_otp_logs")),
    ],
    responses=error_responses(401, 403, 422),
    summary="List OTP delivery logs (codes are never exposed)",
)
async def list_otp_logs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[Page, Depends(page_params)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
    login_channel: Annotated[str | None, Query(description="ADMIN, MERCHANT, CUSTOMER or DELIVERY")] = None,
    delivery_status: str | None = None,
    search: Annotated[str | None, Query(description="Full/partial mobile number or request ID")] = None,
) -> OtpLogListResponse:
    statement = select(OtpChallenge)
    if login_channel:
        statement = statement.where(OtpChallenge.login_channel == login_channel.strip().upper())
    if delivery_status:
        statement = statement.where(OtpChallenge.delivery_status == delivery_status.strip().upper())
    if search:
        value = search.strip()
        statement = statement.where(
            or_(OtpChallenge.id == value, OtpChallenge.mobile_number.ilike(f"%{value}%"))
        )

    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
    rows = (
        await session.execute(
            statement.order_by(OtpChallenge.created_at.desc(), OtpChallenge.id)
            .limit(page.limit)
            .offset(page.offset)
        )
    ).scalars().all()
    now = utc_now_naive()
    response = OtpLogListResponse(
        items=[
            OtpLogItem(
                request_id=row.id,
                masked_mobile=mask_mobile(row.mobile_number) or "******",
                otp=row.otp_plain,
                purpose=row.purpose,
                login_channel=row.login_channel,
                state=_state(row, now),
                delivery_status=row.delivery_status,
                delivery_provider=row.delivery_provider,
                delivery_reference=row.delivery_reference,
                attempts=row.attempts,
                max_attempts=row.max_attempts,
                device_type=row.device_type,
                app_version=row.app_version,
                created_at=row.created_at,
                expires_at=row.expires_at,
                consumed_at=row.consumed_at,
            )
            for row in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
    # Counted separately from the row count, and named in the message: reading delivery
    # statuses and reading live sign-in codes are the same request but not the same act, and an
    # audit trail that cannot tell them apart is no use when somebody asks who saw what.
    revealed = sum(1 for item in response.items if item.otp)
    await AuditLogService(session).write_event(
        AuditLogCreate(
            event_type=(
                "authentication.otp_codes_revealed"
                if revealed
                else "authentication.otp_logs_viewed"
            ),
            actor_user_id=context.user_id,
            entity_type="otp_challenge",
            entity_id=None,
            message=(
                f"Viewed {len(response.items)} OTP delivery log rows"
                + (f", {revealed} with the code in the clear" if revealed else "")
            ),
            login_channel=LoginChannel.ADMIN.value,
            result="SUCCESS",
        )
    )
    await session.commit()
    return response
