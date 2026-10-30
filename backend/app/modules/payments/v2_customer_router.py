"""Customer-only V2 UPI partial-payment endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Path, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, StorageDep
from app.modules.payments.v2_customer_schemas import (
    CreatePaymentIntentRequest,
    PaymentIntentResponse,
    PaymentReceiptUploadResponse,
    SubmitPaymentIntentRequest,
    SubmitPaymentIntentResponse,
)
from app.modules.payments.v2_customer_service import CustomerV2PaymentService
from app.shared.authorization.dependencies import require_login_channel
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/payments", tags=["Customer V2 Payments"])
_customer_only = Depends(require_login_channel(LoginChannel.CUSTOMER))


def build_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: StorageDep,
) -> CustomerV2PaymentService:
    return CustomerV2PaymentService(session, actor, storage)


ServiceDep = Annotated[CustomerV2PaymentService, Depends(build_service)]


@router.post(
    "/intents",
    response_model=PaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_customer_only],
    responses=error_responses(401, 403, 409, 422),
)
async def create_payment_intent(
    payload: CreatePaymentIntentRequest,
    service: ServiceDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=120)],
) -> PaymentIntentResponse:
    return await service.create_intent(payload, idempotency_key)


@router.post(
    "/intents/{paymentIntentId}/submit",
    response_model=SubmitPaymentIntentResponse,
    dependencies=[_customer_only],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def submit_payment_intent(
    payload: SubmitPaymentIntentRequest,
    service: ServiceDep,
    payment_intent_id: Annotated[str, Path(alias="paymentIntentId", max_length=36)],
) -> SubmitPaymentIntentResponse:
    return await service.submit(payment_intent_id, payload)


@router.post(
    "/intents/{paymentIntentId}/receipt",
    response_model=PaymentReceiptUploadResponse,
    dependencies=[_customer_only],
    responses=error_responses(401, 403, 404, 409, 413, 415),
)
async def upload_payment_receipt(
    service: ServiceDep,
    payment_intent_id: Annotated[str, Path(alias="paymentIntentId", max_length=36)],
    file: Annotated[UploadFile, File(description="JPEG or PNG, maximum 5 MB")],
) -> PaymentReceiptUploadResponse:
    uploaded_at = await service.upload_receipt(payment_intent_id, file)
    return PaymentReceiptUploadResponse(
        receipt_url=f"/api/v2/customer/payments/intents/{payment_intent_id}/receipt",
        uploaded_at=uploaded_at,
    )


@router.get(
    "/intents/{paymentIntentId}/receipt",
    dependencies=[_customer_only],
    responses=error_responses(401, 403, 404),
)
async def view_payment_receipt(
    service: ServiceDep,
    payment_intent_id: Annotated[str, Path(alias="paymentIntentId", max_length=36)],
) -> StreamingResponse:
    stream, content_type = await service.receipt_file(payment_intent_id)
    return StreamingResponse(
        stream, media_type=content_type, headers={"Cache-Control": "private, no-store"}
    )
