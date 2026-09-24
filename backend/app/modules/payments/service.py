"""Service layer for payments."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.repository import PaymentRepository
from app.modules.payments.schemas import (
    PaymentMethodResponse,
    PaymentTransactionResponse,
)


class PaymentService:
    def __init__(self, repository: PaymentRepository, session: AsyncSession) -> None:
        self.repository = repository
        self.session = session

    async def list_methods(self, user_id: str) -> list[dict]:
        methods = await self.repository.list_methods_for_user(user_id)
        return [
            PaymentMethodResponse(
                id=m.id,
                type=m.type,
                label=m.label,
                isDefault=m.is_default,
            ).model_dump(by_alias=True)
            for m in methods
        ]

    async def delete_method(self, method_id: str, user_id: str) -> None:
        method = await self.repository.get_method_by_id(method_id, user_id)
        if method is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Payment method not found."},
            )
        await self.repository.delete_method(method)
        await self.session.commit()

    async def list_history(
        self, user_id: str, page: int = 1, limit: int = 20
    ) -> tuple[list[dict], int, int]:
        txns, total_items = await self.repository.list_transactions_for_user(
            user_id, page=page, limit=limit
        )
        items = [
            PaymentTransactionResponse(
                id=t.id,
                amount=t.amount,
                status=t.status,
                createdAt=t.created_at.isoformat(),
            ).model_dump(by_alias=True)
            for t in txns
        ]
        total_pages = max(1, -(-total_items // limit)) if limit > 0 else 1
        return items, total_items, total_pages
