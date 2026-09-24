"""FastAPI router for Orders domain (API Reference §6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import HistoryPeriod, OrderStatus
from app.modules.orders.service import OrderService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import paginated_response, success_response

router = APIRouter(tags=["delivery-orders"])


def get_order_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrderService:
    return OrderService(OrderRepository(session))


@router.get("/orders")
async def list_orders(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: OrderStatus | None = None,
):
    """GET /orders — §6.3: List orders for current driver."""
    items, total_items, _ = await service.list_orders(
        driver_user_id=auth.user_id,
        page=page,
        limit=limit,
        order_status=status.value if status else None,
    )
    return paginated_response(
        items=items,
        page=page,
        total_items=total_items,
        page_size=limit,
    )


@router.get("/orders/history")
async def order_history(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: OrderStatus | None = None,
    period: HistoryPeriod | None = None,
):
    """GET /orders/history — §6.4: Order history with period filters."""
    items, total_items, _ = await service.list_history(
        driver_user_id=auth.user_id,
        page=page,
        limit=limit,
        order_status=status.value if status else None,
        period=period.value if period else None,
    )
    return paginated_response(
        items=items,
        page=page,
        total_items=total_items,
        page_size=limit,
    )


@router.get("/orders/{order_id}")
async def get_order_by_id(
    order_id: str,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    """GET /orders/{orderId} — §6.2: Get order details by ID."""
    order = await service.get_order_by_id(order_id=order_id, driver_user_id=auth.user_id)
    return success_response(order.model_dump(by_alias=True))
