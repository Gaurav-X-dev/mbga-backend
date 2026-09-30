"""The delivery app's routes (API_REFERENCE §6-§10). Delivery channel only."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.driver.schemas import (
    BaseResponse,
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponseData,
    CompletedDeliveryDetailResponseData,
    DriverDeliveryResponse,
    DriverInventoryResponseData,
    DriverProfileResponseData,
    HistoryDeliveriesResponseData,
    OutForDeliveryResponseData,
    UpdateDutyRequest,
    VerifyCustomerOtpRequest,
    VerifyCustomerOtpResponseData,
    VerifyLocationRequest,
    VerifyLocationResponseData,
    UpdateItemsRequest,
    GenerateQrRequest,
    GenerateQrResponseData,
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
) -> DriverService:
    return DriverService(session, actor, settings)


ServiceDep = Annotated[DriverService, Depends(build_service)]

deliveries_router = APIRouter(prefix="/deliveries", tags=["Delivery Deliveries"])
driver_router = APIRouter(prefix="/driver", tags=["Delivery Driver"])


# --- Deliveries ------------------------------------------------------------------------------

@deliveries_router.get(
    "/today",
    response_model=BaseResponse[list[DriverDeliveryResponse]],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def todays_deliveries(service: ServiceDep) -> BaseResponse[list[DriverDeliveryResponse]]:
    data = await service.list_deliveries(DeliveryFilters(scheduled_on=business_today()))
    return BaseResponse(data=data)


@deliveries_router.post(
    "/{deliveryId}/out-for-delivery",
    response_model=BaseResponse[OutForDeliveryResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def out_for_delivery(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> BaseResponse[OutForDeliveryResponseData]:
    return BaseResponse(data=await service.out_for_delivery(delivery_id))


@deliveries_router.post(
    "/{deliveryId}/verify-location",
    response_model=BaseResponse[VerifyLocationResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def verify_location(
    delivery_id: DeliveryIdPath, payload: VerifyLocationRequest, service: ServiceDep
) -> BaseResponse[VerifyLocationResponseData]:
    return BaseResponse(data=await service.verify_location(delivery_id, payload))


@deliveries_router.put(
    "/{deliveryId}/update-items",
    response_model=BaseResponse[DriverDeliveryResponse],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_items(
    delivery_id: DeliveryIdPath, payload: UpdateItemsRequest, service: ServiceDep
) -> BaseResponse[DriverDeliveryResponse]:
    return BaseResponse(data=await service.update_items(delivery_id, payload))


@deliveries_router.post(
    "/{deliveryId}/generate-qr",
    response_model=BaseResponse[GenerateQrResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def generate_qr(
    delivery_id: DeliveryIdPath, payload: GenerateQrRequest, service: ServiceDep
) -> BaseResponse[GenerateQrResponseData]:
    return BaseResponse(data=await service.generate_qr(delivery_id, payload))


@deliveries_router.post(
    "/{deliveryId}/confirm",
    response_model=BaseResponse[ConfirmDeliveryResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def confirm_counts(
    delivery_id: DeliveryIdPath, payload: ConfirmDeliveryRequest, service: ServiceDep
) -> BaseResponse[ConfirmDeliveryResponseData]:
    return BaseResponse(data=await service.confirm_counts(delivery_id, payload))


@deliveries_router.post(
    "/{deliveryId}/verify-customer-otp",
    response_model=BaseResponse[VerifyCustomerOtpResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def verify_customer_otp(
    delivery_id: DeliveryIdPath, payload: VerifyCustomerOtpRequest, service: ServiceDep
) -> BaseResponse[VerifyCustomerOtpResponseData]:
    return BaseResponse(data=await service.verify_customer_otp(delivery_id, payload.otp))


@deliveries_router.get(
    "/{deliveryId}/completed-detail",
    response_model=BaseResponse[CompletedDeliveryDetailResponseData],
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
)
async def delivery_completed_detail(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> BaseResponse[CompletedDeliveryDetailResponseData]:
    return BaseResponse(data=await service.get_completed_detail(delivery_id))


@deliveries_router.get(
    "/history",
    response_model=BaseResponse[HistoryDeliveriesResponseData],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def delivery_history(
    service: ServiceDep,
    period: str = Query("today"),
    page: int = Query(1, ge=1),
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> BaseResponse[HistoryDeliveriesResponseData]:
    return BaseResponse(data=await service.list_history(period, page, limit))


# --- Driver ---------------------------------------------------------------------------------

@driver_router.get(
    "/inventory",
    response_model=BaseResponse[DriverInventoryResponseData],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def van_inventory(service: ServiceDep) -> BaseResponse[DriverInventoryResponseData]:
    return BaseResponse(data=await service.inventory())


@driver_router.patch(
    "/status",
    response_model=BaseResponse[DriverProfileResponseData],
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409),
)
async def set_duty(
    payload: UpdateDutyRequest, service: ServiceDep
) -> BaseResponse[DriverProfileResponseData]:
    return BaseResponse(data=await service.set_duty(payload.on_duty))


@driver_router.get(
    "/profile",
    response_model=BaseResponse[DriverProfileResponseData],
    dependencies=_read_guards,
    responses=error_responses(401, 403),
)
async def my_profile(service: ServiceDep) -> BaseResponse[DriverProfileResponseData]:
    return BaseResponse(data=await service.profile())
