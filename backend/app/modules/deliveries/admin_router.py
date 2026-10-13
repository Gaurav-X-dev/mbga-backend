"""Admin delivery APIs for one explicitly selected merchant."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.deliveries.schemas import DeliverySlipResponse, ReassignDeliveryRequest
from app.modules.deliveries.service import DeliveryService, SlipFilters
from app.modules.vehicles.coverage import available_for_delivery
from app.modules.vehicles.schemas import AvailableVehicleResponse
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/deliveries", tags=["Admin Merchant Deliveries"])

SlipIdPath = Annotated[str, Path(alias="deliveryId", max_length=36)]

_admin_only = Depends(require_login_channel(LoginChannel.ADMIN))
_merchant_scope = Depends(require_permission("merchants.view"))
_read_guards = [_admin_only, _merchant_scope, Depends(require_permission("delivery.view"))]
#: Moving a round is a dispatch decision, so it takes the dispatch permission.
_write_guards = [_admin_only, _merchant_scope, Depends(require_permission("delivery.confirm"))]


def build_service(
    actor: AdminMerchantActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DeliveryService:
    """FastAPI caches `get_db_session` per request, so the actor and the service share one
    session and therefore one transaction."""
    return DeliveryService(session, actor, settings)


ServiceDep = Annotated[DeliveryService, Depends(build_service)]


@router.get(
    "",
    response_model=list[DeliverySlipResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="List delivery slips",
)
async def list_deliveries(
    service: ServiceDep,
    slip_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="`SCHEDULED` | `DISPATCHED` | `ON_LOCATION` | `DELIVERED` | `FAILED` | `ALL`.",
            max_length=20,
        ),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            description="Slip number, order number, customer name or mobile, vehicle, driver.",
            max_length=120,
        ),
    ] = None,
) -> list[DeliverySlipResponse]:
    """The dispatch board, ordered as a work queue.

    Dispatched slips first, then what still has to go out, then failures, and delivered slips
    last - they need nobody.
    """
    return await service.list_slips(SlipFilters(status=slip_status, search=search))


@router.get(
    "/{deliveryId}",
    response_model=DeliverySlipResponse,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
    summary="Delivery slip detail",
)
async def get_delivery(delivery_id: SlipIdPath, service: ServiceDep) -> DeliverySlipResponse:
    """One slip. Another merchant's slip is a 404, never a 403."""
    return await service.get(delivery_id)


@router.get(
    "/{deliveryId}/available-vehicles",
    response_model=list[AvailableVehicleResponse],
    dependencies=_read_guards,
    summary="Vehicles mapped to this delivery pincode",
)
async def get_available_vehicles(
    delivery_id: SlipIdPath,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> list[AvailableVehicleResponse]:
    return await available_for_delivery(session, actor.require_merchant_id(), delivery_id)


@router.patch(
    "/{deliveryId}/assignment",
    response_model=DeliverySlipResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Move a round to another van, crew or day",
)
async def reassign_delivery(
    delivery_id: SlipIdPath, payload: ReassignDeliveryRequest, service: ServiceDep
) -> DeliverySlipResponse:
    """Change a slip without losing the order.

    Only what is sent changes. A slip that has already left the godown is not moved - those are
    failed and raised again, because the cylinders are on that van and the code is in the
    customer's hand.
    """
    return await service.reassign(delivery_id, payload)
