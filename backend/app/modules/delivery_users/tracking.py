"""Read-only admin tracking over existing driver profiles and GPS breadcrumbs."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.delivery_users.admin_router import _response
from app.modules.delivery_users.models import DeliveryProfile, DriverLocationLog
from app.modules.delivery_users.schemas import DeliveryUserResponse
from app.modules.users.models import User
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.date_time.business_calendar import IST_TIMEZONE
from app.shared.exceptions.api_error import ApiError
from app.shared.geo.distance import haversine_metres

STATIONARY_RADIUS = 30
MAX_PING_GAP = 300
STALE_AFTER = 300
OBSERVATION_HOURS = 24
POINT_LIMIT = 500
ROUTE_LIMIT = 10000


def local_time(value: datetime) -> datetime:
    # Location tables deliberately store IST wall time (migration 0055), unlike other tables.
    return (
        value.replace(tzinfo=IST_TIMEZONE)
        if value.tzinfo is None
        else value.astimezone(IST_TIMEZONE)
    )


def timestamp(value: datetime | None) -> str | None:
    return local_time(value).isoformat() if value else None


def eligible(profile: DeliveryProfile, user: User) -> bool:
    return (
        profile.status == "ACTIVE"
        and user.status == "ACTIVE"
        and profile.approval_status == "APPROVED"
        and bool(profile.on_duty)
    )


def valid_coordinates(latitude, longitude) -> bool:
    return (
        latitude is not None
        and longitude is not None
        and isfinite(float(latitude))
        and isfinite(float(longitude))
        and -90 <= float(latitude) <= 90
        and -180 <= float(longitude) <= 180
    )


class TrackingPolicy(BaseModel):
    stationary_radius_metres: int = STATIONARY_RADIUS
    max_ping_gap_seconds: int = MAX_PING_GAP
    stale_after_seconds: int = STALE_AFTER
    observation_hours: int = OBSERVATION_HOURS
    point_limit: int = POINT_LIMIT


class TrackedDriver(DeliveryUserResponse):
    account_status: str
    can_view_logs: bool
    current_latitude: float | None = None
    current_longitude: float | None = None
    location_accuracy: float | None = None
    last_location_at: str | None = None
    location_state: str = "UNAVAILABLE"
    stationary_seconds: int | None = None
    stationary_since: str | None = None
    stationary_until: str | None = None
    stationary_sample_count: int = 0
    stationary_is_lower_bound: bool = False


class TrackingList(BaseModel):
    items: list[TrackedDriver]
    total: int
    limit: int
    offset: int
    generated_at: str
    policy: TrackingPolicy = Field(default_factory=TrackingPolicy)


class LocationLogItem(BaseModel):
    id: str
    latitude: float
    longitude: float
    accuracy: float | None = None
    recorded_at: str
    received_at: str
    is_future: bool


class TrackingHistory(BaseModel):
    driver: TrackedDriver
    items: list[LocationLogItem]
    total: int
    limit: int
    offset: int
    from_date: date
    to_date: date
    generated_at: str


class TrackingRoute(BaseModel):
    items: list[LocationLogItem]
    total: int
    limit: int = ROUTE_LIMIT
    truncated: bool
    from_date: date
    to_date: date
    generated_at: str
    stationary_radius_metres: int = STATIONARY_RADIUS
    max_ping_gap_seconds: int = MAX_PING_GAP


def observed_stay(latitude, longitude, last_at, points, now):
    if last_at is None:
        return {}
    anchor = local_time(last_at)
    if anchor > now + timedelta(seconds=60):
        return {}
    earliest = previous = anchor
    seen = {anchor}
    stopped = False
    window_start = now - timedelta(hours=OBSERVATION_HOURS)
    for point in points[:POINT_LIMIT]:
        moment = local_time(point["recorded_at"])
        if moment > anchor:
            continue
        if (
            moment < window_start
            or (previous - moment).total_seconds() > MAX_PING_GAP
            or not valid_coordinates(point["latitude"], point["longitude"])
            or haversine_metres(
                latitude, longitude, float(point["latitude"]), float(point["longitude"])
            )
            > STATIONARY_RADIUS
        ):
            stopped = True
            break
        earliest = previous = moment
        seen.add(moment)
    if len(seen) < 2:
        return {"stationary_sample_count": len(seen)}
    return {
        "stationary_seconds": int((anchor - earliest).total_seconds()),
        "stationary_since": timestamp(earliest),
        "stationary_until": timestamp(anchor),
        "stationary_sample_count": len(seen),
        "stationary_is_lower_bound": not stopped
        and (
            len(points) > POINT_LIMIT or earliest <= window_start + timedelta(seconds=MAX_PING_GAP)
        ),
    }


class TrackingService:
    def __init__(self, session: AsyncSession, merchant_id: str, now: datetime | None = None):
        self.session = session
        self.merchant_id = merchant_id
        self.now = local_time(now or datetime.now(IST_TIMEZONE))

    def _base(self):
        latest_id = (
            select(DriverLocationLog.id)
            .where(
                DriverLocationLog.driver_id == DeliveryProfile.id,
                DriverLocationLog.merchant_id == self.merchant_id,
            )
            .order_by(
                DriverLocationLog.recorded_at.desc(),
                DriverLocationLog.created_at.desc(),
                DriverLocationLog.id.desc(),
            )
            .limit(1)
            .correlate(DeliveryProfile)
            .scalar_subquery()
        )
        return (
            select(DeliveryProfile, User, DriverLocationLog)
            .join(User, User.id == DeliveryProfile.user_id)
            .outerjoin(
                DriverLocationLog,
                (DriverLocationLog.id == latest_id)
                & (DriverLocationLog.driver_id == DeliveryProfile.id)
                & (DriverLocationLog.merchant_id == self.merchant_id),
            )
            .where(
                DeliveryProfile.merchant_id == self.merchant_id,
                DeliveryProfile.delivery_user_type == "DRIVER",
            )
        )

    async def _points(self, rows):
        ids = [profile.id for profile, user, _log in rows if eligible(profile, user)]
        if not ids:
            return {}
        ranked = (
            select(
                DriverLocationLog.driver_id,
                DriverLocationLog.latitude,
                DriverLocationLog.longitude,
                DriverLocationLog.recorded_at,
                func.row_number()
                .over(
                    partition_by=DriverLocationLog.driver_id,
                    order_by=(
                        DriverLocationLog.recorded_at.desc(),
                        DriverLocationLog.created_at.desc(),
                        DriverLocationLog.id.desc(),
                    ),
                )
                .label("position"),
            )
            .where(
                DriverLocationLog.merchant_id == self.merchant_id,
                DriverLocationLog.driver_id.in_(ids),
                DriverLocationLog.recorded_at
                >= (self.now - timedelta(hours=OBSERVATION_HOURS)).replace(tzinfo=None),
                DriverLocationLog.recorded_at
                <= (self.now + timedelta(seconds=60)).replace(tzinfo=None),
            )
            .subquery()
        )
        points = await self.session.execute(
            select(ranked)
            .where(ranked.c.position <= POINT_LIMIT + 1)
            .order_by(ranked.c.driver_id, ranked.c.position)
        )
        grouped = defaultdict(list)
        for point in points.mappings():
            grouped[point["driver_id"]].append(point)
        return grouped

    def _view(self, profile, user, log, points):
        data = _response(profile, user).model_dump()
        view = TrackedDriver(
            **data, account_status=user.status, can_view_logs=eligible(profile, user)
        )
        lat, lon, last, accuracy = (
            profile.current_latitude,
            profile.current_longitude,
            profile.last_ping_at,
            profile.location_accuracy,
        )
        if log and (
            not valid_coordinates(lat, lon)
            or last is None
            or local_time(log.recorded_at) > local_time(last)
        ):
            lat, lon, last, accuracy = log.latitude, log.longitude, log.recorded_at, log.accuracy
        if not valid_coordinates(lat, lon):
            return view
        view.current_latitude, view.current_longitude = float(lat), float(lon)
        view.location_accuracy = float(accuracy) if accuracy is not None else None
        view.last_location_at = timestamp(last)
        if last is None:
            view.location_state = "UNKNOWN_TIME"
            return view
        age = (self.now - local_time(last)).total_seconds()
        view.location_state = "FUTURE" if age < -60 else "STALE" if age > STALE_AFTER else "RECENT"
        if view.can_view_logs:
            for key, value in observed_stay(
                view.current_latitude, view.current_longitude, last, points, self.now
            ).items():
                setattr(view, key, value)
        return view

    async def listing(self, *, search=None, status=None, on_duty=None, limit=20, offset=0):
        filters = []
        if search and search.strip():
            pattern = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.full_name).like(pattern),
                    User.mobile_number.like(pattern),
                    func.lower(DeliveryProfile.employee_code).like(pattern),
                )
            )
        if status:
            filters.append(DeliveryProfile.status == status.upper())
        if on_duty is not None:
            filters.append(DeliveryProfile.on_duty.is_(on_duty))
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(DeliveryProfile)
                .join(User, User.id == DeliveryProfile.user_id)
                .where(
                    DeliveryProfile.merchant_id == self.merchant_id,
                    DeliveryProfile.delivery_user_type == "DRIVER",
                    *filters,
                )
            )
            or 0
        )
        rows = (
            await self.session.execute(
                self._base()
                .where(*filters)
                .order_by(User.full_name, DeliveryProfile.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        points = await self._points(rows)
        return TrackingList(
            items=[
                self._view(profile, user, log, points.get(profile.id, []))
                for profile, user, log in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
            generated_at=timestamp(self.now),
        )

    async def _history_context(self, driver_id, from_date, to_date):
        row = (
            await self.session.execute(self._base().where(DeliveryProfile.id == driver_id))
        ).one_or_none()
        if row is None:
            raise ApiError("DELIVERY_USER_NOT_FOUND", 404, "Driver was not found in this agency.")
        profile, user, _log = row
        if not eligible(profile, user):
            raise ApiError(
                "DRIVER_TRACKING_UNAVAILABLE",
                409,
                "Location logs are available only for active, approved, on-duty drivers.",
            )
        end = to_date or self.now.date()
        start = from_date or end
        if start > end or (end - start).days > 30:
            raise ApiError(
                "INVALID_DATE_RANGE",
                422,
                "Select a date range of up to 31 days, with the start before the end.",
            )
        filters = [
            DriverLocationLog.merchant_id == self.merchant_id,
            DriverLocationLog.driver_id == profile.id,
            DriverLocationLog.recorded_at >= datetime.combine(start, time.min),
            DriverLocationLog.recorded_at < datetime.combine(end + timedelta(days=1), time.min),
        ]
        return row, start, end, filters

    async def route(self, driver_id, *, from_date=None, to_date=None):
        history = await self.history(
            driver_id, from_date=from_date, to_date=to_date, limit=ROUTE_LIMIT, offset=0
        )
        return TrackingRoute(
            items=list(reversed(history.items)),
            total=history.total,
            limit=ROUTE_LIMIT,
            truncated=history.total > ROUTE_LIMIT,
            from_date=history.from_date,
            to_date=history.to_date,
            generated_at=history.generated_at,
        )

    async def history(self, driver_id, *, from_date=None, to_date=None, limit=50, offset=0):
        row, start, end, filters = await self._history_context(driver_id, from_date, to_date)
        profile, user, log = row
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(DriverLocationLog).where(*filters)
            )
            or 0
        )
        logs = (
            await self.session.scalars(
                select(DriverLocationLog)
                .where(*filters)
                .order_by(
                    DriverLocationLog.recorded_at.desc(),
                    DriverLocationLog.created_at.desc(),
                    DriverLocationLog.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        points = await self._points([row])
        return TrackingHistory(
            driver=self._view(profile, user, log, points.get(profile.id, [])),
            items=[
                LocationLogItem(
                    id=item.id,
                    latitude=float(item.latitude),
                    longitude=float(item.longitude),
                    accuracy=float(item.accuracy) if item.accuracy is not None else None,
                    recorded_at=timestamp(item.recorded_at),
                    received_at=timestamp(item.created_at),
                    is_future=local_time(item.recorded_at) > self.now + timedelta(seconds=60),
                )
                for item in logs
            ],
            total=total,
            limit=limit,
            offset=offset,
            from_date=start,
            to_date=end,
            generated_at=timestamp(self.now),
        )


router = APIRouter(
    prefix="/live-location",
    tags=["Admin Live Location Tracking"],
    dependencies=[
        Depends(require_login_channel(LoginChannel.ADMIN)),
        Depends(require_permission("merchants.view")),
        Depends(require_permission("delivery_users.view")),
    ],
)
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=TrackingList)
async def list_tracking(
    session: SessionDep,
    actor: AdminMerchantActorDep,
    response: Response,
    search: Annotated[str | None, Query(max_length=160)] = None,
    status: Annotated[str | None, Query(max_length=30)] = None,
    on_duty: Annotated[bool | None, Query(alias="onDuty")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    response.headers["Cache-Control"] = "private, no-store"
    return await TrackingService(session, actor.require_merchant_id()).listing(
        search=search, status=status, on_duty=on_duty, limit=limit, offset=offset
    )


@router.get("/{driver_id}/logs", response_model=TrackingHistory)
async def tracking_history(
    driver_id: str,
    session: SessionDep,
    actor: AdminMerchantActorDep,
    response: Response,
    from_date: Annotated[date | None, Query(alias="fromDate")] = None,
    to_date: Annotated[date | None, Query(alias="toDate")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    response.headers["Cache-Control"] = "private, no-store"
    return await TrackingService(session, actor.require_merchant_id()).history(
        driver_id, from_date=from_date, to_date=to_date, limit=limit, offset=offset
    )


@router.get("/{driver_id}/route", response_model=TrackingRoute)
async def tracking_route(
    driver_id: str,
    session: SessionDep,
    actor: AdminMerchantActorDep,
    response: Response,
    from_date: Annotated[date | None, Query(alias="fromDate")] = None,
    to_date: Annotated[date | None, Query(alias="toDate")] = None,
):
    response.headers["Cache-Control"] = "private, no-store"
    return await TrackingService(session, actor.require_merchant_id()).route(
        driver_id, from_date=from_date, to_date=to_date
    )
