"""Agency arrival-radius overrides; platform defaults remain admin-owned."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.merchants.models import Merchant
from app.modules.platform_settings.service import load
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
admin_router = APIRouter(
    prefix="/settings/merchants",
    tags=["Admin App Settings"],
    dependencies=[Depends(require_login_channel(LoginChannel.ADMIN))],
)
merchant_router = APIRouter(
    prefix="/settings",
    tags=["Merchant App Settings"],
    dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT))],
)


class RadiusUpdate(BaseModel):
    delivery_radius_metres: int | None = Field(
        default=None, alias="deliveryRadiusMeters", ge=1, le=100000
    )
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RadiusResponse(BaseModel):
    merchant_id: str = Field(alias="merchantId")
    delivery_radius_metres: int = Field(alias="deliveryRadiusMeters")
    delivery_radius_km: float = Field(alias="deliveryRadiusKm")
    default_radius_metres: int = Field(alias="defaultRadiusMeters")
    override_radius_metres: int | None = Field(alias="overrideRadiusMeters")
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


async def merchant_row(session: AsyncSession, merchant_id: str, *, lock: bool = False) -> Merchant:
    query = select(Merchant).where(Merchant.id == merchant_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    return row


async def effective_radius(session: AsyncSession, merchant_id: str) -> int:
    merchant = await merchant_row(session, merchant_id)
    if merchant.delivery_radius_metres is not None:
        return merchant.delivery_radius_metres
    return (await load(session)).delivery_radius_metres


async def radius_view(session: AsyncSession, merchant_id: str) -> RadiusResponse:
    merchant = await merchant_row(session, merchant_id)
    default = (await load(session)).delivery_radius_metres
    radius = (
        merchant.delivery_radius_metres if merchant.delivery_radius_metres is not None else default
    )
    return RadiusResponse(
        merchant_id=merchant.id,
        delivery_radius_metres=radius,
        delivery_radius_km=radius / 1000,
        default_radius_metres=default,
        override_radius_metres=merchant.delivery_radius_metres,
    )


async def save_radius(
    session: AsyncSession, actor, merchant_id: str, payload: RadiusUpdate
) -> RadiusResponse:
    row = await merchant_row(session, merchant_id, lock=True)
    if "delivery_radius_metres" in payload.model_fields_set:
        before = row.delivery_radius_metres
        row.delivery_radius_metres = payload.delivery_radius_metres
        row.updated_at = datetime.now(UTC)
        if before != row.delivery_radius_metres:
            await AuditLogService(session).write_event(
                AuditLogCreate(
                    event_type="APP_SETTINGS_CHANGED",
                    actor_user_id=actor.user_id,
                    entity_type="merchant",
                    entity_id=row.id,
                    message=f"Delivery radius changed from {before} to {row.delivery_radius_metres} metres (null inherits platform default)",
                    login_channel=actor.login_channel.value,
                    result="SUCCESS",
                )
            )
    await session.commit()
    return await radius_view(session, merchant_id)


@admin_router.get(
    "/{merchant_id}",
    response_model=RadiusResponse,
    dependencies=[Depends(require_permission("platform_settings.view"))],
)
async def admin_read(merchant_id: str, session: SessionDep):
    return await radius_view(session, merchant_id)


@admin_router.patch(
    "/{merchant_id}",
    response_model=RadiusResponse,
    dependencies=[Depends(require_permission("platform_settings.manage"))],
)
async def admin_update(
    merchant_id: str, payload: RadiusUpdate, session: SessionDep, actor: ActorDep
):
    return await save_radius(session, actor, merchant_id, payload)


@merchant_router.get(
    "", response_model=RadiusResponse, dependencies=[Depends(require_permission("delivery.view"))]
)
async def merchant_read(session: SessionDep, actor: ActorDep):
    return await radius_view(session, actor.require_merchant_id())


@merchant_router.patch(
    "",
    response_model=RadiusResponse,
    dependencies=[Depends(require_permission("delivery.confirm"))],
)
async def merchant_update(payload: RadiusUpdate, session: SessionDep, actor: ActorDep):
    return await save_radius(session, actor, actor.require_merchant_id(), payload)
