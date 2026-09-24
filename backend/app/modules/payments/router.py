"""FastAPI router for Payments domain (API Reference §11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.service import PaymentService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import paginated_response, success_response

router = APIRouter(tags=["delivery-payments"])


def get_payment_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PaymentService:
    return PaymentService(PaymentRepository(session), session)


@router.get("/payments/methods")
async def list_payment_methods(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
):
    """GET /payments/methods — §11.1: List payment methods."""
    methods = await service.list_methods(user_id=auth.user_id)
    return success_response(methods)


@router.delete("/payments/methods/{method_id}")
async def delete_payment_method(
    method_id: str,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
):
    """DELETE /payments/methods/{methodId} — §11.2: Delete payment method."""
    await service.delete_method(method_id=method_id, user_id=auth.user_id)
    return success_response(None)


@router.get("/payments/history")
async def payment_history(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """GET /payments/history — §11.3: Payment transaction history."""
    items, total_items, _ = await service.list_history(
        user_id=auth.user_id, page=page, limit=limit
    )
    return paginated_response(
        items=items,
        page=page,
        total_items=total_items,
        page_size=limit,
    )
