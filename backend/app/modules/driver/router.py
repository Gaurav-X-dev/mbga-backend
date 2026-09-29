"""The delivery app's routes (API_REFERENCE §6-§10). Delivery channel only.

Paths follow the app's contract rather than the platform's house style, because the app is
already built against them: `/deliveries/today`, `/driver/profile`, `/driver/status`. A token
minted on any other channel is refused here, so a merchant session cannot read a driver's queue
and a driver cannot reach the dispatch board.

Two guards on every route, and they answer different questions. `driver_user_id` in the query's
`WHERE` decides *which* deliveries are yours - that is scoping, and it is what makes another
driver's slip a 404. The permission decides whether you may work at all: `deliveries.view` to
read, `deliveries.update_status` to act. Both are seeded onto the `driver` and `helper` roles, so
nothing has to be granted per deployment, and taking the role away stops the app without
touching a slip.

Payments (§11) are deliberately absent. The platform has no payment module, and the app's own
reference marks those endpoints "confirm scope before building".
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.driver.schemas import (
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponse,
    DriverDeliveryResponse,
    DriverInventoryResponse,
    DriverProfileResponse,
    StartDeliveryRequest,
    StartDeliveryResponse,
    UpdateDutyRequest,
    VerifyCustomerOtpRequest,
    VerifyCustomerOtpResponse,
)
from app.modules.driver.service import DeliveryFilters, DriverService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.date_time.business_calendar import business_today
from app.shared.exceptions.openapi import error_responses

DeliveryIdPath = Annotated[str, Path(alias="deliveryId", max_length=36)]

_delivery_only = Depends(require_login_channel(LoginChannel.DELIVERY))
#: Reading the queue and the driver's own record.
_read_guards = [_delivery_only, Depends(require_permission("deliveries.view"))]
#: Setting off, counting at the gate, completing a handover, going on or off duty.
_write_guards = [_delivery_only, Depends(require_permission("deliveries.update_status"))]


def build_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DriverService:
    """FastAPI caches `get_db_session` per request, so the actor and the service share one
    session and therefore one transaction."""
    return DriverService(session, actor, settings)


ServiceDep = Annotated[DriverService, Depends(build_service)]

deliveries_router = APIRouter(prefix="/deliveries", tags=["Delivery Deliveries"])
driver_router = APIRouter(prefix="/driver", tags=["Delivery Driver"])


# --- Deliveries ------------------------------------------------------------------------------


@deliveries_router.get(
    "/today",
    response_model=list[DriverDeliveryResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Today's deliveries",
)
async def todays_deliveries(service: ServiceDep) -> list[DriverDeliveryResponse]:
    """The driver's queue for today (§6.1).

    Today is read on the **IST business calendar**, not UTC: a slip scheduled for the 28th
    belongs to the 28th in the godown, and a driver opening the app at 06:00 IST must not still
    be looking at yesterday's list.

    Ordered as work: what is on the van, then what is still to load, then what is done.
    """
    return await service.list_deliveries(
        DeliveryFilters(scheduled_on=business_today())
    )


@deliveries_router.get(
    "",
    response_model=list[DriverDeliveryResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="My deliveries",
)
async def my_deliveries(
    service: ServiceDep,
    scheduled_date: Annotated[
        date | None, Query(alias="scheduledDate", description="Limit to one delivery day.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DriverDeliveryResponse]:
    """Every slip addressed to this driver, newest first."""
    return await service.list_deliveries(
        DeliveryFilters(scheduled_on=scheduled_date, limit=limit)
    )


@deliveries_router.get(
    "/history",
    response_model=list[DriverDeliveryResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Completed deliveries",
)
async def delivery_history(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DriverDeliveryResponse]:
    """What this driver has already settled - delivered or failed (§6.4)."""
    return await service.list_deliveries(DeliveryFilters(settled_only=True, limit=limit))


@deliveries_router.get(
    "/{deliveryId}",
    response_model=DriverDeliveryResponse,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
    summary="Delivery detail",
)
async def delivery_detail(delivery_id: DeliveryIdPath, service: ServiceDep) -> DriverDeliveryResponse:
    """One drop. Another driver's delivery is a 404, never a 403."""
    return await service.get_delivery(delivery_id)


@deliveries_router.post(
    "/{deliveryId}/start",
    response_model=StartDeliveryResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Start the trip",
)
async def start_delivery(
    delivery_id: DeliveryIdPath, payload: StartDeliveryRequest, service: ServiceDep
) -> StartDeliveryResponse:
    """Record that the driver has set off, and where from (§7.1).

    `isAtLocation` is a hint for the UI, not a gate: it is true whenever the distance cannot be
    measured, because most delivery sites have no recorded coordinates and a driver standing at
    the gate must still be able to work. Pressing Start twice is safe - the first departure time
    is kept and the position refreshed.
    """
    return await service.start(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/confirm",
    response_model=ConfirmDeliveryResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Record the counts",
)
async def confirm_counts(
    delivery_id: DeliveryIdPath, payload: ConfirmDeliveryRequest, service: ServiceDep
) -> ConfirmDeliveryResponse:
    """What the driver counted at the gate (§7.2).

    **This does not complete the delivery.** No stock moves, the order does not advance and the
    customer is not told - that happens at `verify-customer-otp`. Saving the counts separately is
    what lets the app be backgrounded between counting cylinders and the customer finding their
    code.

    A part delivery is refused with `422`: the ledger books the slip's whole load at handover, so
    accepting a smaller number would take the full quantity off the shelf while the driver still
    had some on the van.
    """
    return await service.confirm_counts(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/verify-customer-otp",
    response_model=VerifyCustomerOtpResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Verify the customer's code",
)
async def verify_customer_otp(
    delivery_id: DeliveryIdPath, payload: VerifyCustomerOtpRequest, service: ServiceDep
) -> VerifyCustomerOtpResponse:
    """Complete the handover (§7.3).

    The customer reads out the four-digit code their "out for delivery" notification carried.
    This runs the **same** confirm the office runs: stock comes off the books, the order becomes
    DELIVERED and the customer is notified.

    A wrong code costs one attempt out of a generous budget - a misheard digit at a noisy gate is
    the common case, and a locked slip means a wasted trip.
    """
    return await service.verify_customer_otp(delivery_id, payload.otp)


# --- Profile ---------------------------------------------------------------------------------


@driver_router.get(
    "/profile",
    response_model=DriverProfileResponse,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="My profile",
)
async def my_profile(service: ServiceDep) -> DriverProfileResponse:
    """The driver's own record (§8.1)."""
    return await service.profile()


@driver_router.patch(
    "/status",
    response_model=DriverProfileResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409),
    summary="Go on or off duty",
)
async def set_duty(payload: UpdateDutyRequest, service: ServiceDep) -> DriverProfileResponse:
    """The driver's own shift switch (§8.2).

    Going off duty is refused with `409` while a van of theirs is still out: those cylinders are
    on the road under this driver's name, and signing off would leave a dispatched slip with
    nobody responsible for it.
    """
    return await service.set_duty(payload.on_duty)


@driver_router.get(
    "/inventory",
    response_model=DriverInventoryResponse,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="What is on my van",
)
async def van_inventory(service: ServiceDep) -> DriverInventoryResponse:
    """Computed from this driver's dispatched slips, never stored (§10).

    A van-stock table would be a second place the same cylinders are counted, and it would drift
    the first time a delivery was confirmed from the office rather than the app.
    """
    return await service.inventory()
