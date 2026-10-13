"""Admin inventory APIs for one explicitly selected merchant."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.inventory.constants import DEFAULT_MOVEMENT_LIMIT, MAX_MOVEMENT_LIMIT
from app.modules.inventory.schemas import (
    InventorySnapshotResponse,
    RecordStockMovementRequest,
    StockMovementResponse,
)
from app.modules.inventory.service import InventoryService, MovementFilters
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/inventory", tags=["Admin Merchant Inventory"])

_admin_only = Depends(require_login_channel(LoginChannel.ADMIN))
_merchant_scope = Depends(require_permission("merchants.view"))
_read_guards = [_admin_only, _merchant_scope, Depends(require_permission("inventory.view"))]
_write_guards = [_admin_only, _merchant_scope, Depends(require_permission("inventory.adjust"))]


def build_service(
    actor: AdminMerchantActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventoryService:
    """FastAPI caches `get_db_session` per request, so the actor and the service share one
    session and therefore one transaction."""
    return InventoryService(session, actor)


ServiceDep = Annotated[InventoryService, Depends(build_service)]


@router.get(
    "",
    response_model=InventorySnapshotResponse,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Inventory snapshot",
)
async def inventory_snapshot(service: ServiceDep) -> InventorySnapshotResponse:
    """Live counts for all five cylinder types, with alerts derived from them.

    Alerts are computed here rather than stored, so a refill clears a low-stock warning the
    moment it is recorded and nothing has to go back and mark it resolved.
    """
    return await service.snapshot()


@router.get(
    "/movements",
    response_model=list[StockMovementResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Stock movement history",
)
async def stock_movements(
    service: ServiceDep,
    cylinder_type: Annotated[
        str | None,
        Query(alias="cylinderType", description="A cylinder type code, or `ALL`.", max_length=40),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=MAX_MOVEMENT_LIMIT,
            description=f"Rows to return (default {DEFAULT_MOVEMENT_LIMIT}).",
        ),
    ] = None,
) -> list[StockMovementResponse]:
    """The ledger, newest first. Every count on the screen above is explained by a row here."""
    return await service.movements(MovementFilters(cylinder_type=cylinder_type, limit=limit))


@router.post(
    "/movements",
    response_model=StockMovementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 409, 422),
    summary="Record a stock movement",
)
async def record_movement(
    payload: RecordStockMovementRequest,
    service: ServiceDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Optional. Retrying with the same key returns the first movement rather than booking a second.",
        ),
    ] = None,
) -> StockMovementResponse:
    """Book a refill, a plant return, a damage write-off or an audit correction.

    `DISPATCHED` and `EMPTIES_COLLECTED` are refused here - they are written by the delivery
    endpoints against a real slip. A `409` means the movement would have taken a bucket
    negative, and nothing was changed.

    The app refetches `GET /inventory` afterwards (spec §11.3) rather than patching the counts
    from this response, because one movement can change the alerts on other cards too.
    """
    return await service.record_with_idempotency(payload, idempotency_key)
