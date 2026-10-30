"""Merchant V2 review endpoints for customer FIFO UPI collections."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, StorageDep
from app.modules.payments.schemas import ReconcilePaymentRequest
from app.modules.payments.v2_customer_schemas import PaymentCollectionResponse
from app.modules.payments.v2_merchant_service import MerchantV2PaymentService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/payment-collections", tags=["Merchant V2 Payments"])
_merchant = Depends(require_login_channel(LoginChannel.MERCHANT))


def build_service(
    actor: ActorDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: StorageDep,
) -> MerchantV2PaymentService:
    return MerchantV2PaymentService(session, actor, storage)


ServiceDep = Annotated[MerchantV2PaymentService, Depends(build_service)]
CollectionId = Annotated[str, Path(alias="collectionId", max_length=36)]


@router.get(
    "",
    response_model=list[PaymentCollectionResponse],
    dependencies=[_merchant, Depends(require_permission("payments.view"))],
    responses=error_responses(401, 403, 422),
)
async def list_payment_collections(
    service: ServiceDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
) -> list[PaymentCollectionResponse]:
    return await service.list_collections(status)


@router.get(
    "/{collectionId}",
    response_model=PaymentCollectionResponse,
    dependencies=[_merchant, Depends(require_permission("payments.view"))],
    responses=error_responses(401, 403, 404),
)
async def get_payment_collection(
    collection_id: CollectionId, service: ServiceDep
) -> PaymentCollectionResponse:
    return await service.get_collection(collection_id)


@router.get(
    "/{collectionId}/receipt",
    dependencies=[_merchant, Depends(require_permission("payments.view"))],
    responses=error_responses(401, 403, 404),
)
async def view_payment_receipt(
    collection_id: CollectionId, service: ServiceDep
) -> StreamingResponse:
    stream, content_type = await service.receipt_file(collection_id)
    return StreamingResponse(
        stream, media_type=content_type, headers={"Cache-Control": "private, no-store"}
    )


@router.post(
    "/{collectionId}/reconcile",
    response_model=PaymentCollectionResponse,
    dependencies=[_merchant, Depends(require_permission("payments.reconcile"))],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def reconcile_payment_collection(
    collection_id: CollectionId,
    payload: ReconcilePaymentRequest,
    service: ServiceDep,
) -> PaymentCollectionResponse:
    return await service.reconcile(collection_id, payload)
