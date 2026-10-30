"""Additive customer-only inventory reads. No stock or delivery mutation endpoints."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.dependencies import CustomerActorDep
from app.modules.inventory.customer_schemas import (
    FiltersResponse,
    InventoryResponse,
    MovementsResponse,
)
from app.modules.inventory.customer_service import CustomerInventoryService
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/inventory", tags=["Customer Inventory"])


def build_service(
    actor: CustomerActorDep, session: Annotated[AsyncSession, Depends(get_db_session)]
):
    return CustomerInventoryService(session, actor)


ServiceDep = Annotated[CustomerInventoryService, Depends(build_service)]
CylinderQuery = Annotated[str | None, Query(alias="cylinderType", min_length=1, max_length=40)]


@router.get("", response_model=InventoryResponse, responses=error_responses(401, 403, 404, 422))
async def inventory(service: ServiceDep, cylinder_type: CylinderQuery = None):
    """All-time current holding. Labels are sizes only; render variant separately.

    Eligibility controls zero-balance choices; historicalOnly rows preserve actual past
    handovers and are not offered for ordering. Internal cylinderType codes are identifiers,
    not customer-facing text. This endpoint never applies date filters.
    """
    return await service.snapshot(cylinder_type)


@router.get("/filters", response_model=FiltersResponse, responses=error_responses(401, 403, 404))
async def inventory_filters(service: ServiceDep):
    """Eligible types plus this customer's historical types. LOT/VOT stay separate codes."""
    return await service.filters()


@router.get(
    "/movements", response_model=MovementsResponse, responses=error_responses(401, 403, 404, 422)
)
async def movements(
    service: ServiceDep,
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    cylinder_type: CylinderQuery = None,
    movement_type: Annotated[
        Literal["DELIVERY", "RETURN"] | None, Query(alias="movementType")
    ] = None,
    variant: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    order_id: Annotated[str | None, Query(alias="orderId", min_length=1, max_length=36)] = None,
    delivery_slip_id: Annotated[
        str | None, Query(alias="deliverySlipId", min_length=1, max_length=36)
    ] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    sort_order: Annotated[Literal["asc", "desc"], Query(alias="sortOrder")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
):
    """Completed handovers only, with inclusive IST dates and summary before pagination.

    occurredAt uses delivered_at; legacy slips without it use updated_at, explicitly
    identified by timestampSource=UPDATED_AT_FALLBACK. Missing historical per-type return
    counts follow the existing balance rule (zero); never infer them from slip totals.
    """
    return await service.movements(
        date_from=date_from,
        date_to=date_to,
        cylinder_type=cylinder_type,
        movement_type=movement_type,
        variant=variant,
        order_id=order_id,
        delivery_slip_id=delivery_slip_id,
        search=search,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
