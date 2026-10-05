"""The admin panel's Settings screen.

One resource rather than an endpoint per value: the screen reads and saves a form, and splitting
it would mean a panel that has to know which call changes which field. New settings are added as
fields here, and a client that does not send one leaves it alone.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.dependencies import ActorDep
from app.modules.orders.cutoff import clock_12h, clock_24h
from app.modules.platform_settings import service
from app.modules.platform_settings.models import PlatformSettings
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/settings", tags=["admin-settings"])
VIEW = Depends(require_permission("platform_settings.view"))
MANAGE = Depends(require_permission("platform_settings.manage"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class PlatformSettingsResponse(BaseModel):
    """What the Settings screen renders, including the two forms of the cut-off it displays."""

    order_cutoff_hour: int = Field(alias="orderCutoffHour")
    #: `"16:00"`. The form of the time the apps parse.
    order_cutoff_time: str = Field(alias="orderCutoffTime")
    #: `"4:00 PM"`. The form a person reads, so the panel does not build it itself and drift.
    order_cutoff_label: str = Field(alias="orderCutoffLabel")
    updated_by_name: str | None = Field(default=None, alias="updatedByName")
    updated_at: str | None = Field(default=None, alias="updatedAt")

    model_config = _CAMEL


class PlatformSettingsUpdate(BaseModel):
    """Every field optional: the panel sends what it changed, not the whole world."""

    #: 0-23, IST. Refused outside that rather than silently making every order same-day.
    order_cutoff_hour: int | None = Field(default=None, alias="orderCutoffHour", ge=0, le=23)

    model_config = _CAMEL


def _view(settings: PlatformSettings) -> PlatformSettingsResponse:
    return PlatformSettingsResponse(
        order_cutoff_hour=settings.order_cutoff_hour,
        order_cutoff_time=clock_24h(settings.order_cutoff_hour),
        order_cutoff_label=clock_12h(settings.order_cutoff_hour),
        updated_by_name=settings.updated_by_name,
        updated_at=settings.updated_at.isoformat() if settings.updated_at else None,
    )


@router.get(
    "",
    response_model=PlatformSettingsResponse,
    dependencies=[VIEW],
    responses=error_responses(401, 403),
    summary="Platform operating settings",
)
async def read_settings(session: SessionDep) -> PlatformSettingsResponse:
    settings = await service.load(session)
    await session.commit()
    return _view(settings)


@router.patch(
    "",
    response_model=PlatformSettingsResponse,
    dependencies=[MANAGE],
    responses=error_responses(401, 403, 422),
    summary="Change platform operating settings",
)
async def update_settings(
    payload: PlatformSettingsUpdate, session: SessionDep, actor: ActorDep
) -> PlatformSettingsResponse:
    """Takes effect on the next order placed.

    Orders already placed keep the cut-off they were promised: it is frozen onto the order at
    placement, so moving this does not rewrite what a customer was told last week.
    """
    settings = await service.update(
        session, actor, order_cutoff_hour=payload.order_cutoff_hour
    )
    return _view(settings)
