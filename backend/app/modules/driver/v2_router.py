"""Delivery V2 payment endpoints; V1 delivery routes remain frozen."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, StorageDep
from app.modules.driver.schemas import (
    ConfirmDeliveryResponseData,
    GenerateQrRequest,
    GenerateQrResponseData,
    PaymentProofUploadResponseData,
    PaymentSummaryResponseData,
    VerifyCustomerOtpRequest,
)
from app.modules.driver.v2_schemas import (
    CompletedDeliveryDetailResponseDataV2,
    ConfirmDeliveryRequestV2,
    VerifyCustomerOtpResponseDataV2,
)
from app.modules.driver.v2_service import DriverV2Service
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

DeliveryIdPath = Annotated[str, Path(alias="deliveryId", max_length=36)]
_delivery_only = Depends(require_login_channel(LoginChannel.DELIVERY))
_read_guards = [_delivery_only, Depends(require_permission("deliveries.view"))]
_write_guards = [
    _delivery_only,
    Depends(require_permission("deliveries.update_status")),
]


def build_v2_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: StorageDep,
) -> DriverV2Service:
    return DriverV2Service(session, actor, settings, storage)


ServiceDep = Annotated[DriverV2Service, Depends(build_v2_service)]
router = APIRouter(prefix="/deliveries", tags=["Delivery V2 Payments"])


@router.post(
    "/{deliveryId}/generate-qr",
    response_model=GenerateQrResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def generate_qr_v2(
    delivery_id: DeliveryIdPath,
    payload: GenerateQrRequest,
    service: ServiceDep,
) -> GenerateQrResponseData:
    return await service.generate_qr(delivery_id, payload)


@router.post(
    "/{deliveryId}/payment-proof",
    response_model=PaymentProofUploadResponseData,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 413, 415, 422),
)
async def upload_payment_proof_v2(
    delivery_id: DeliveryIdPath,
    service: ServiceDep,
    file: Annotated[UploadFile, File(description="JPEG or PNG, maximum 5 MB")],
    captured_at: Annotated[datetime, Form(alias="capturedAt")],
) -> PaymentProofUploadResponseData:
    return await service.upload_payment_proof(delivery_id, file, captured_at)


@router.get(
    "/{deliveryId}/payment-proof",
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
)
async def view_payment_proof_v2(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> StreamingResponse:
    stream, content_type = await service.payment_proof_file(delivery_id)
    return StreamingResponse(stream, media_type=content_type)


@router.post(
    "/{deliveryId}/confirm",
    response_model=ConfirmDeliveryResponseData,
    dependencies=_write_guards,
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
async def confirm_delivery_v2(
    delivery_id: DeliveryIdPath,
    payload: ConfirmDeliveryRequestV2,
    service: ServiceDep,
) -> ConfirmDeliveryResponseData:
    return await service.confirm_counts(delivery_id, payload)


@router.post(
    "/{deliveryId}/verify-customer-otp",
    response_model=VerifyCustomerOtpResponseDataV2,
    dependencies=_write_guards,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def verify_customer_otp_v2(
    delivery_id: DeliveryIdPath,
    payload: VerifyCustomerOtpRequest,
    service: ServiceDep,
) -> VerifyCustomerOtpResponseDataV2:
    return await service.verify_customer_otp_v2(delivery_id, payload.otp)


@router.get(
    "/{deliveryId}/payment-summary",
    response_model=PaymentSummaryResponseData,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
)
async def payment_summary_v2(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> PaymentSummaryResponseData:
    return await service.payment_summary_v2(delivery_id)


@router.get(
    "/{deliveryId}/completed-detail",
    response_model=CompletedDeliveryDetailResponseDataV2,
    dependencies=_read_guards,
    responses=error_responses(401, 403, 404),
)
async def completed_detail_v2(
    delivery_id: DeliveryIdPath, service: ServiceDep
) -> CompletedDeliveryDetailResponseDataV2:
    return await service.get_completed_detail_v2(delivery_id)
