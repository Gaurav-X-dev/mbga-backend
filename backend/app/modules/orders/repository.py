"""Repository for orders associated with a delivery driver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.deliveries.models import Delivery
from app.modules.orders.models import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id_for_driver(self, order_id: str, driver_user_id: str) -> Order | None:
        stmt = (
            select(Order)
            .join(Delivery, Delivery.order_id == Order.id)
            .where(
                (Order.id == order_id) | (Order.order_number == order_id),
                Delivery.driver_user_id == driver_user_id,
            )
            .options(selectinload(Order.items))
        )
        return await self.session.scalar(stmt)

    async def list_for_driver(
        self,
        driver_user_id: str,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[Order], int]:
        stmt = (
            select(Order)
            .join(Delivery, Delivery.order_id == Order.id)
            .where(Delivery.driver_user_id == driver_user_id)
        )
        if status:
            stmt = stmt.where(Order.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_items = (await self.session.scalar(count_stmt)) or 0

        stmt = (
            stmt.options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all()), total_items

    async def list_history_for_driver(
        self,
        driver_user_id: str,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
        period: str | None = None,
    ) -> tuple[list[Order], int]:
        stmt = (
            select(Order)
            .join(Delivery, Delivery.order_id == Order.id)
            .where(Delivery.driver_user_id == driver_user_id)
        )
        if status:
            stmt = stmt.where(Order.status == status)

        now = datetime.now(UTC)
        if period == "today":
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            stmt = stmt.where(Order.created_at >= start_of_day)
        elif period == "week":
            start_of_week = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            stmt = stmt.where(Order.created_at >= start_of_week)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_items = (await self.session.scalar(count_stmt)) or 0

        stmt = (
            stmt.options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all()), total_items
