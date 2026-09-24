"""Repository for payment methods and transactions."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import PaymentMethod, PaymentTransaction


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_methods_for_user(self, user_id: str) -> list[PaymentMethod]:
        stmt = (
            select(PaymentMethod)
            .where(PaymentMethod.user_id == user_id)
            .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def get_method_by_id(self, method_id: str, user_id: str) -> PaymentMethod | None:
        stmt = select(PaymentMethod).where(
            PaymentMethod.id == method_id,
            PaymentMethod.user_id == user_id,
        )
        return await self.session.scalar(stmt)

    async def delete_method(self, method: PaymentMethod) -> None:
        await self.session.delete(method)
        await self.session.flush()

    async def list_transactions_for_user(
        self, user_id: str, page: int = 1, limit: int = 20
    ) -> tuple[list[PaymentTransaction], int]:
        count_stmt = (
            select(func.count())
            .select_from(PaymentTransaction)
            .where(PaymentTransaction.user_id == user_id)
        )
        total_items = (await self.session.scalar(count_stmt)) or 0

        stmt = (
            select(PaymentTransaction)
            .where(PaymentTransaction.user_id == user_id)
            .order_by(PaymentTransaction.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all()), total_items
