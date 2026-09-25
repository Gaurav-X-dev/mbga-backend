"""Delivery & dispatch routes, merchant channel only (spec §10, endpoints 25-28).

No `build_*_router(channel)` factory here, unlike orders and notifications, because there is one
caller. A slip is the godown's document: it names the vehicle and the crew, and it is the
instruction to load a van. A customer follows their own order through the order endpoints, which
tell them what they need - placed, out for delivery, delivered - without exposing which driver is
carrying whose cylinders.

Two permissions, matching spec §2.1: `delivery.view` reads, `delivery.confirm` dispatches and
confirms. Manager and Godown Incharge hold both.

Route order matters: nothing sits at `/deliveries/{id}` that could swallow a fixed segment, but
the two action routes are declared after the detail route on purpose so the id pattern stays
obvious to anyone reading the file top to bottom.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.deliveries.schemas import (
    ConfirmDeliveryRequest,
    CreateDeliverySlipRequest,
    DeliverySlipResponse,
    FailDeliveryRequest,
)
from app.modules.deliveries.service import DeliveryService, SlipFilters
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/deliveries", tags=["Merchant Deliveries"])

SlipIdPath = Annotated[str, Path(alias="deliveryId", max_length=36)]

_merchant_only = Depends(require_login_channel(LoginChannel.MERCHANT))
_read_guards = [_merchant_only, Depends(require_permission("delivery.view"))]
_write_guards = [_merchant_only, Depends(require_permission("delivery.confirm"))]


def build_service(
    actor: ActorDep,
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
        Query(alias="status", description="`SCHEDULED` | `DISPATCHED` | `DELIVERED` | `FAILED` | `ALL`.", max_length=20),
    ] = None,
    search: Annotated[
        str | None,
        Query(description="Slip number, order number, customer name or mobile, vehicle, driver.", max_length=120),
    ] = None,
) -> list[DeliverySlipResponse]:
    """The dispatch board, ordered as a work queue.

    Dispatched slips first, then what still has to go out, then failures, and delivered slips
    last - they need nobody.
    """
    return await service.list_slips(SlipFilters(status=slip_status, search=search))


@router.post(
    "",
    response_model=DeliverySlipResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Schedule a delivery",
)
async def create_delivery(payload: CreateDeliverySlipRequest, service: ServiceDep) -> DeliverySlipResponse:
    """Raise a slip against a confirmed order, with a vehicle and a crew.

    **Not one of the spec's four delivery endpoints.** §10 never says where a slip comes from -
    the Phase 1 frontend had them seeded in a mock - and without this the module cannot be used
    at all. Added the way `POST /orders/{id}/cancel` was.

    No stock moves here: this is the loading instruction, and the stock check happens at dispatch,
    because a slip is often raised the evening before the refill truck arrives. Naming a
    `driverUserId` is what sends "New delivery assigned" to that driver's phone.
    """
    return await service.create(payload)


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


@router.post(
    "/{deliveryId}/dispatch",
    response_model=DeliverySlipResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409),
    summary="Mark as dispatched",
)
async def dispatch_delivery(delivery_id: SlipIdPath, service: ServiceDep) -> DeliverySlipResponse:
    """Send the van out (spec §10.3). Empty body.

    Atomic across four systems: filled stock comes off the shelf, the slip becomes `DISPATCHED`,
    the order moves to `OUT_FOR_DELIVERY` with a "Vehicle … · Driver" note, and the customer is
    told. A `409` means either the slip is not `SCHEDULED` or a line is short on stock - and in
    the second case **no count changed**, so recording a refill and retrying is all it takes.
    """
    return await service.dispatch(delivery_id)


@router.post(
    "/{deliveryId}/confirm",
    response_model=DeliverySlipResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Confirm delivery",
)
async def confirm_delivery(
    delivery_id: SlipIdPath, payload: ConfirmDeliveryRequest, service: ServiceDep
) -> DeliverySlipResponse:
    """Record the handover (spec §10.4).

    The customer reads out the four-digit code the dispatch notification gave them. Empties the
    driver brought back are booked into stock, the order becomes `DELIVERED`, and
    `pendingPickup` is whatever did not come back.
    """
    return await service.confirm(delivery_id, payload)


@router.post(
    "/{deliveryId}/fail",
    response_model=DeliverySlipResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Mark a delivery failed",
)
async def fail_delivery(
    delivery_id: SlipIdPath, payload: FailDeliveryRequest, service: ServiceDep
) -> DeliverySlipResponse:
    """Record a van that came back without delivering.

    Also an addition: `FAILED` is in the spec's `DeliveryStatus` and the list filters on it, but
    no endpoint sets it - and a dispatched slip that never delivered has stock sitting on a van.
    With `returnedToStock` the cylinders go back on the shelf against this slip, so the ledger
    still reconciles. The order stays `OUT_FOR_DELIVERY`: walking it backwards would erase the
    fact that it once went out, so rescheduling is a new slip and the office's decision.
    """
    return await service.fail(delivery_id, payload)
