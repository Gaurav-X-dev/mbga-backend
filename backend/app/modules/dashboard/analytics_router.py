"""The numbers behind the head-office dashboard charts.

One endpoint rather than six, because the screen draws them together and a single round trip
keeps the panel honest about what "as of now" means: six separate calls can disagree with each
other by seconds and make a reader doubt the whole page.

Everything here is derived from rows the platform already writes — merchants, sign-in
sessions, OTP challenges, KYC applications. Nothing is estimated or back-filled: a quiet
month reports zero rather than being smoothed away.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.authentication.session_service import utc_now_naive
from app.modules.customers.models import KycApplication
from app.modules.merchants.models import Merchant
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])
VIEW = Depends(require_permission("dashboard.view"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

CHANNELS = ("ADMIN", "MERCHANT", "CUSTOMER", "DELIVERY")


class MerchantGrowthPoint(BaseModel):
    """`merchants` is the running total at the end of the month, `onboarded` the new ones."""

    label: str
    month: date
    onboarded: int
    merchants: int


class OtpDayPoint(BaseModel):
    label: str
    day: date
    success: int
    failed: int


class ActivityDayPoint(BaseModel):
    label: str
    day: date
    sign_ins: int


class ChannelPoint(BaseModel):
    channel: str
    sessions: int


class StatusCount(BaseModel):
    status: str
    count: int


class DashboardAnalytics(BaseModel):
    merchant_growth: list[MerchantGrowthPoint]
    otp_attempts: list[OtpDayPoint]
    user_activity: list[ActivityDayPoint]
    login_channels: list[ChannelPoint]
    kyc_status: list[StatusCount]
    otp_today_total: int
    otp_today_success_rate: float
    kyc_pending: int


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _months_back(today: date, count: int) -> list[date]:
    months = [_month_start(today)]
    for _ in range(count - 1):
        first = months[0]
        previous = date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)
        months.insert(0, previous)
    return months


async def _counts_by_day(
    session: AsyncSession, statement: Select, days: Sequence[date]
) -> dict[date, int]:
    """Buckets `(timestamp, count)` rows into a date map, so gaps can be filled with zero."""
    rows = (await session.execute(statement)).all()
    result: dict[date, int] = {day: 0 for day in days}
    for value, count in rows:
        if value is None:
            continue
        key = value.date() if isinstance(value, datetime) else value
        if key in result:
            result[key] += int(count or 0)
    return result


@router.get(
    "/analytics",
    response_model=DashboardAnalytics,
    dependencies=[VIEW],
    responses=error_responses(401, 403, 422),
    summary="Dashboard chart series",
)
async def dashboard_analytics(
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90, description="Window for the daily series.")] = 7,
    months: Annotated[int, Query(ge=1, le=24, description="Window for merchant growth.")] = 6,
) -> DashboardAnalytics:
    now = utc_now_naive()
    today = now.date()
    day_list = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    window_start = datetime.combine(day_list[0], datetime.min.time())
    month_list = _months_back(today, months)

    # --- Merchant growth ------------------------------------------------------------------
    # Counted per month and then accumulated, so the line is a running total rather than a
    # sawtooth of monthly intake. Bucketed in Python rather than with a SQL month function:
    # those differ between MariaDB and SQLite, and a merchant network is small enough that
    # reading the creation dates costs nothing.
    created_dates = (
        await session.scalars(select(Merchant.created_at).where(Merchant.created_at.is_not(None)))
    ).all()
    per_month: dict[date, int] = {}
    for value in created_dates:
        key = _month_start(value.date() if isinstance(value, datetime) else value)
        per_month[key] = per_month.get(key, 0) + 1

    # Everything created before the window still counts towards the running total.
    running = sum(count for month, count in per_month.items() if month < month_list[0])
    merchant_growth: list[MerchantGrowthPoint] = []
    for month in month_list:
        onboarded = per_month.get(month, 0)
        running += onboarded
        merchant_growth.append(
            MerchantGrowthPoint(
                label=month.strftime("%b"), month=month, onboarded=onboarded, merchants=running
            )
        )

    # --- OTP outcomes ---------------------------------------------------------------------
    # A challenge that was consumed is a completed sign-in; one that expired unconsumed is a
    # failure. Suppressed challenges (no eligible account) are excluded: nothing was ever sent,
    # so counting them as failures would make the success rate look worse than reality.
    otp_day = func.date(OtpChallenge.created_at)
    otp_rows = (
        await session.execute(
            select(otp_day, OtpChallenge.consumed_at.is_not(None).label("ok"), func.count())
            .where(OtpChallenge.created_at >= window_start, OtpChallenge.dispatch_suppressed.is_(False))
            .group_by(otp_day, "ok")
        )
    ).all()
    success_by_day = {day: 0 for day in day_list}
    failed_by_day = {day: 0 for day in day_list}
    for value, ok, count in otp_rows:
        if value is None:
            continue
        key = value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
        if key not in success_by_day:
            continue
        (success_by_day if ok else failed_by_day)[key] += int(count or 0)

    otp_attempts = [
        OtpDayPoint(
            label=day.strftime("%d %b"), day=day, success=success_by_day[day], failed=failed_by_day[day]
        )
        for day in day_list
    ]
    today_success = success_by_day.get(today, 0)
    today_failed = failed_by_day.get(today, 0)
    today_total = today_success + today_failed

    # --- Panel activity and channel mix ---------------------------------------------------
    session_day = func.date(LoginSession.created_at)
    activity = await _counts_by_day(
        session,
        select(session_day, func.count())
        .where(LoginSession.created_at >= window_start, LoginSession.login_channel == "ADMIN")
        .group_by(session_day),
        day_list,
    )
    user_activity = [
        ActivityDayPoint(label=day.strftime("%a"), day=day, sign_ins=activity[day]) for day in day_list
    ]

    channel_rows = (
        await session.execute(
            select(LoginSession.login_channel, func.count())
            .where(LoginSession.created_at >= window_start)
            .group_by(LoginSession.login_channel)
        )
    ).all()
    by_channel = {(value or "").upper(): int(count or 0) for value, count in channel_rows}
    login_channels = [ChannelPoint(channel=name.title(), sessions=by_channel.get(name, 0)) for name in CHANNELS]

    # --- KYC ------------------------------------------------------------------------------
    kyc_rows = (
        await session.execute(select(KycApplication.status, func.count()).group_by(KycApplication.status))
    ).all()
    kyc_status = [StatusCount(status=str(value), count=int(count or 0)) for value, count in kyc_rows]
    kyc_pending = next((item.count for item in kyc_status if item.status.upper() == "PENDING"), 0)

    return DashboardAnalytics(
        merchant_growth=merchant_growth,
        otp_attempts=otp_attempts,
        user_activity=user_activity,
        login_channels=login_channels,
        kyc_status=kyc_status,
        otp_today_total=today_total,
        otp_today_success_rate=round(today_success / today_total * 100, 1) if today_total else 0.0,
        kyc_pending=kyc_pending,
    )
