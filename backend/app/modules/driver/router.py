"""The delivery app's routes (API_REFERENCE §6-§10). Delivery channel only."""

from typing import Annotated

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, StorageDep
from app.modules.driver.schemas import (
    AvailableCylinderTypesResponseData,
    CancelDeliveryRequest,
    CancelDeliveryResponseData,
    CancellationReasonsResponseData,
    CompletedDeliveryDetailResponseData,
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponseData,
    DriverDeliveryResponse,
    DaySummaryResponseData,
    DriverInventoryResponseData,
    DriverProfileResponseData,
    GenerateQrRequest,
    GenerateQrResponseData,
    HistoryDeliveriesResponseData,
    OutForDeliveryBulkRequest,
    OutForDeliveryResponseData,
    PaymentSummaryResponseData,
    PaymentProofUploadResponseData,
    UpdateDutyRequest,
    UpdateItemsRequest,
    VerifyCustomerOtpRequest,
    VerifyCustomerOtpResponseData,
    VerifyLocationRequest,
    VerifyLocationResponseData,
)
from app.modules.driver.service import DeliveryFilters, DriverService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.date_time.business_calendar import business_today
from app.shared.exceptions.openapi import error_responses

DeliveryIdPath = Annotated[str, Path(alias="deliveryId", max_length=36)]

_delivery_only = Depends(require_login_channel(LoginChannel.DELIVERY))
_read_guards = [_delivery_only, Depends(require_permission("deliveries.view"))]
_write_guards = [_delivery_only, Depends(require_permission("deliveries.update_status"))]


def build_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: StorageDep,
) -> DriverService:
    return DriverService(session, actor, settings, storage)


ServiceDep = Annotated[DriverService, Depends(build_service)]

deliveries_router = APIRouter(prefix="/deliveries", tags=["Delivery Deliveries"])
driver_router = APIRouter(prefix="/driver", tags=["Delivery Driver"])
# Reference data for the delivery app, at the channel root. Not under /deliveries: it is
# not about one delivery, and a literal path there shares a space with /{deliveryId}.
reference_router = APIRouter(tags=["Delivery Reference"])


# --- Deliveries ------------------------------------------------------------------------------


@deliveries_router.get(
    "/today",
    response_model=list[DriverDeliveryResponse],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def todays_deliveries(service: ServiceDep) -> list[DriverDeliveryResponse]:
    """Today's round, whatever state each stop is in.

    Completed and failed stops stay on the list: a driver reads it to see how far through the
    day he is, and a round that emptied as he worked would tell him nothing. `status` says
    which is which - `COMPLETED`, `FAILED`, `ON_LOCATION`, `PENDING` - and a stop the office
    cancelled under him reads `FAILED`, beside the notification that told him so.
    """
    return await service.list_deliveries(DeliveryFilters(scheduled_on=business_today()))


@deliveries_router.get(
    "/{deliveryId}/available-cylinder-types",
    response_model=AvailableCylinderTypesResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404, 409),
    summary="Cylinder choices for the doorstep Update Order sheet",
)
async def available_cylinder_types(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> AvailableCylinderTypesResponseData:
    """Return only the cylinder types and effective prices allowed for this customer."""
    return await service.available_cylinder_types(delivery_id)


@deliveries_router.post(
    "/out-for-delivery",
    response_model=list[OutForDeliveryResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Set off with a whole round",
)
async def out_for_delivery_many(
    payload: OutForDeliveryBulkRequest, service: ServiceDep
) -> list[OutForDeliveryResponseData]:
    """The van has left the godown carrying all of these.

    All or nothing: one press is one event, so slips that half moved would describe a van that is
    both out and not. Each order moves to `OUT_FOR_DELIVERY` and each customer is told.
    """
    return await service.out_for_delivery_many(payload.delivery_ids)


@deliveries_router.post(
    "/{deliveryId}/out-for-delivery",
    response_model=OutForDeliveryResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def out_for_delivery(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> OutForDeliveryResponseData:
    return await service.out_for_delivery(delivery_id)


@deliveries_router.post(
    "/{deliveryId}/cancel",
    response_model=CancelDeliveryResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Cancel an unsuccessful delivery with customer OTP",
)
async def cancel_delivery(
    delivery_id: DeliveryIdPath,
    payload: CancelDeliveryRequest,
    service: ServiceDep,
) -> CancelDeliveryResponseData:
    """Close the dispatched slip as failed and its order as cancelled.

    The same OTP sent when the driver set off proves that the customer acknowledged the outcome.
    A later delivery requires a new order; there is no reschedule action.
    """
    return await service.cancel_delivery(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/verify-location",
    response_model=VerifyLocationResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="I am on location",
)
async def verify_location(
    delivery_id: DeliveryIdPath, payload: VerifyLocationRequest, service: ServiceDep
) -> VerifyLocationResponseData:
    """Capture the driver's GPS fix and publish ON_LOCATION to all three apps."""
    return await service.verify_location(delivery_id, payload)


@deliveries_router.put(
    "/{deliveryId}/update-items",
    response_model=DriverDeliveryResponse,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_items(
    delivery_id: DeliveryIdPath, payload: UpdateItemsRequest, service: ServiceDep
) -> DriverDeliveryResponse:
    return await service.update_items(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/generate-qr",
    response_model=GenerateQrResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Generate UPI QR as Base64 PNG",
)
async def generate_qr(
    delivery_id: DeliveryIdPath, payload: GenerateQrRequest, service: ServiceDep
) -> GenerateQrResponseData:
    """Generate a QR locally; this does not contact or verify with a payment gateway."""
    return await service.generate_qr(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/payment-proof",
    response_model=PaymentProofUploadResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 413, 415, 422),
    summary="Upload UPI payment proof",
)
async def upload_payment_proof(
    delivery_id: DeliveryIdPath,
    service: ServiceDep,
    file: Annotated[UploadFile, File(description="JPEG or PNG, maximum 5 MB")],
    captured_at: Annotated[datetime, Form(alias="capturedAt")],
) -> PaymentProofUploadResponseData:
    return await service.upload_payment_proof(delivery_id, file, captured_at)


@deliveries_router.get(
    "/{deliveryId}/payment-proof",
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
    summary="View this delivery's payment proof",
)
async def view_payment_proof(delivery_id: DeliveryIdPath, service: ServiceDep):
    stream, content_type = await service.payment_proof_file(delivery_id)
    return StreamingResponse(stream, media_type=content_type)


@deliveries_router.post(
    "/{deliveryId}/confirm",
    response_model=ConfirmDeliveryResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def confirm_counts(
    delivery_id: DeliveryIdPath, payload: ConfirmDeliveryRequest, service: ServiceDep
) -> ConfirmDeliveryResponseData:
    return await service.confirm_counts(delivery_id, payload)


@deliveries_router.post(
    "/{deliveryId}/verify-customer-otp",
    response_model=VerifyCustomerOtpResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def verify_customer_otp(
    delivery_id: DeliveryIdPath, payload: VerifyCustomerOtpRequest, service: ServiceDep
) -> VerifyCustomerOtpResponseData:
    return await service.verify_customer_otp(delivery_id, payload.otp)


@deliveries_router.get(
    "/{deliveryId}/payment-summary",
    response_model=PaymentSummaryResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
    summary="What to collect at this gate, and what was already owed",
)
async def payment_summary(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> PaymentSummaryResponseData:
    """The payment screen's figures, worked out together so they agree with each other."""
    return await service.payment_summary(delivery_id)


@deliveries_router.get(
    "/{deliveryId}/completed-detail",
    response_model=CompletedDeliveryDetailResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
)
async def delivery_completed_detail(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> CompletedDeliveryDetailResponseData:
    return await service.get_completed_detail(delivery_id)


@deliveries_router.get(
    "/history",
    response_model=HistoryDeliveriesResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def delivery_history(
    service: ServiceDep,
    period: str = Query("today"),
    page: int = Query(1, ge=1),
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    status: str = Query(
        "ALL",
        description=(
            "completed, failed, or ALL for both - the same words each row carries. "
            "Anything else means both."
        ),
    ),
) -> HistoryDeliveriesResponseData:
    """Settled rounds, newest first.

    `total` is how many match the filter, not how many are on this page - a screen counting
    the rows it was handed is counting one page.
    """
    return await service.list_history(period, page, limit, status)


# --- Driver ---------------------------------------------------------------------------------


@driver_router.get(
    "/day-summary",
    response_model=DaySummaryResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Today's handover and empties, size by size",
)
async def day_summary(service: ServiceDep) -> DaySummaryResponseData:
    """What this driver has handed over and taken back today.

    The two questions the godown asks at the end of a round - how many cylinders went out, how
    many shells came back - with the per-size breakdown behind each. Totals and lines are the
    same numbers read two ways, so the screen can print the arithmetic.

    Completed deliveries only. `GET /driver/inventory` answers the other question: what is on
    the van right now.
    """
    return await service.day_summary()


@driver_router.get(
    "/inventory",
    response_model=DriverInventoryResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def van_inventory(service: ServiceDep) -> DriverInventoryResponseData:
    return await service.inventory()


@driver_router.patch(
    "/status",
    response_model=DriverProfileResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409),
)
async def set_duty(payload: UpdateDutyRequest, service: ServiceDep) -> DriverProfileResponseData:
    return await service.set_duty(payload.on_duty)


@driver_router.get(
    "/profile",
    response_model=DriverProfileResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def my_profile(service: ServiceDep) -> DriverProfileResponseData:
    return await service.profile()


# --- Reference data -------------------------------------------------------------------------


@reference_router.get(
    "/cancellation-reasons",
    response_model=CancellationReasonsResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403),
    summary="Why a delivery may be cancelled",
)
async def cancellation_reasons(service: ServiceDep) -> CancellationReasonsResponseData:
    """The cancel screen's dropdown. Codes are fixed; labels are reworded in `constants`."""
    return await service.cancellation_reasons()
