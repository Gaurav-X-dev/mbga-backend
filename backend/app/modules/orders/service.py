"""Service layer for order operations."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.modules.orders.models import Order
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import (
    OrderItemResponse,
    OrderResponse,
)


def order_to_response(order: Order) -> OrderResponse:
    completed_at_str: str | None = None
    if order.completed_at:
        completed_at_str = order.completed_at.strftime("%I:%M %p")

    items = [
        OrderItemResponse(
            id=item.id,
            kind=item.kind,
            label=item.label,
            quantity=item.quantity,
        )
        for item in (order.items or [])
    ]

    return OrderResponse(
        id=order.id,
        orderNumber=order.order_number,
        customerName=order.customer_name,
        customerPhone=order.customer_phone,
        address=order.address,
        timeSlotStart=order.time_slot_start,
        timeSlotEnd=order.time_slot_end,
        status=order.status,
        distanceKm=order.distance_km,
        completedAt=completed_at_str,
        items=items,
    )


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    async def get_order_by_id(self, order_id: str, driver_user_id: str) -> OrderResponse:
        order = await self.repository.get_by_id_for_driver(order_id, driver_user_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Order not found."},
            )
        return order_to_response(order)

    async def list_orders(
        self,
        driver_user_id: str,
        page: int = 1,
        limit: int = 20,
        order_status: str | None = None,
    ) -> tuple[list[dict], int, int]:
        orders, total_items = await self.repository.list_for_driver(
            driver_user_id=driver_user_id,
            page=page,
            limit=limit,
            status=order_status,
        )
        items = [order_to_response(o).model_dump(by_alias=True) for o in orders]
        total_pages = max(1, -(-total_items // limit)) if limit > 0 else 1
        return items, total_items, total_pages

    async def list_history(
        self,
        driver_user_id: str,
        page: int = 1,
        limit: int = 20,
        order_status: str | None = None,
        period: str | None = None,
    ) -> tuple[list[dict], int, int]:
        orders, total_items = await self.repository.list_history_for_driver(
            driver_user_id=driver_user_id,
            page=page,
            limit=limit,
            status=order_status,
            period=period,
        )
        items = [order_to_response(o).model_dump(by_alias=True) for o in orders]
        total_pages = max(1, -(-total_items // limit)) if limit > 0 else 1
        return items, total_items, total_pages
