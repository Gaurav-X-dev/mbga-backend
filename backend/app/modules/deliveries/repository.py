"""Repository for delivery operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.deliveries.models import Delivery
from app.modules.orders.models import Order


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id_for_driver(
        self, delivery_id: str, driver_user_id: str
    ) -> Delivery | None:
        stmt = (
            select(Delivery)
            .where(
                (Delivery.id == delivery_id) | (Delivery.order_id == delivery_id),
                Delivery.driver_user_id == driver_user_id,
            )
            .options(
                selectinload(Delivery.order).selectinload(Order.items)
            )
        )
        return await self.session.scalar(stmt)

    async def list_today_deliveries(self, driver_user_id: str) -> list[Delivery]:
        now = datetime.now(UTC)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        stmt = (
            select(Delivery)
            .where(
                Delivery.driver_user_id == driver_user_id,
                Delivery.created_at >= start_of_day,
                Delivery.created_at < end_of_day,
            )
            .options(
                selectinload(Delivery.order).selectinload(Order.items)
            )
            .order_by(Delivery.created_at.asc())
        )
        result = await self.session.scalars(stmt)
        deliveries = list(result.all())

        # If no deliveries found for today yet, return all pending/in_progress deliveries for this driver
        if not deliveries:
            fallback_stmt = (
                select(Delivery)
                .where(
                    Delivery.driver_user_id == driver_user_id,
                    Delivery.status.in_(["pending", "in_progress"]),
                )
                .options(
                    selectinload(Delivery.order).selectinload(Order.items)
                )
                .order_by(Delivery.created_at.asc())
            )
            fallback_result = await self.session.scalars(fallback_stmt)
            deliveries = list(fallback_result.all())

        return deliveries

    async def save(self, delivery: Delivery) -> Delivery:
        self.session.add(delivery)
        await self.session.flush()
        return delivery
