"""Cylinder reservations enforced when a merchant accepts an order."""

from collections import defaultdict
from collections.abc import Sequence

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_catalogue.models import CylinderTypeDefinition
from app.modules.inventory.models import StockItem
from app.modules.orders.constants import OrderStatus
from app.modules.orders.models import Order, OrderItem
from app.shared.exceptions.api_error import ApiError

_RESERVING_STATUSES = (
    OrderStatus.CONFIRMED.value,
    OrderStatus.OUT_FOR_DELIVERY.value,
    OrderStatus.ON_LOCATION.value,
)


async def ensure_confirmation_stock(
    session: AsyncSession,
    merchant_id: str,
    orders: Sequence[Order],
) -> None:
    """Refuse new confirmations that exceed uncommitted filled stock.

    The stock row is the serialization lock shared with inventory movements. Locking reads are
    intentional: MySQL REPEATABLE READ must see a confirmation committed while this request was
    waiting, otherwise two simultaneous confirmations could both spend the same cylinders.
    """
    new_orders = [order for order in orders if order.status == OrderStatus.PLACED.value]
    if not new_orders:
        return

    order_ids = [order.id for order in new_orders]
    requested_rows = (
        await session.execute(
            select(OrderItem.cylinder_type, OrderItem.quantity).where(
                OrderItem.order_id.in_(order_ids)
            )
        )
    ).all()
    requested: dict[str, int] = defaultdict(int)
    for cylinder_type, quantity in requested_rows:
        requested[cylinder_type] += int(quantity)

    types = sorted(requested)
    stock_rows = list(
        await session.scalars(
            select(StockItem)
            .where(
                StockItem.merchant_id == merchant_id,
                StockItem.cylinder_type.in_(types),
            )
            .order_by(StockItem.cylinder_type)
            .with_for_update()
        )
    )
    stock = {row.cylinder_type: int(row.filled) for row in stock_rows}

    reserved_rows = (
        await session.execute(
            select(OrderItem.cylinder_type, OrderItem.quantity)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.merchant_id == merchant_id,
                Order.status.in_(_RESERVING_STATUSES),
                Order.id.not_in(order_ids),
                OrderItem.cylinder_type.in_(types),
            )
            .with_for_update()
        )
    ).all()
    reserved: dict[str, int] = defaultdict(int)
    for cylinder_type, quantity in reserved_rows:
        reserved[cylinder_type] += int(quantity)

    labels = {
        row.code: row.short_label or row.label
        for row in await session.scalars(
            select(CylinderTypeDefinition).where(CylinderTypeDefinition.code.in_(types))
        )
    }
    for cylinder_type in types:
        available = max(stock.get(cylinder_type, 0) - reserved[cylinder_type], 0)
        needed = requested[cylinder_type]
        if needed > available:
            label = labels.get(cylinder_type, cylinder_type)
            raise ApiError(
                "INSUFFICIENT_STOCK",
                status.HTTP_409_CONFLICT,
                f"Insufficient stock for {label}: {available} available, {needed} required.",
            )
