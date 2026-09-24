"""Payment models — §11 of the API Reference."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    __table_args__ = (Index("ix_payment_methods_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(
        String(30)
    )  # upi | card | cash | wallet
    label: Mapped[str] = mapped_column(String(160))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        Index("ix_payment_transactions_user_id", "user_id"),
        Index("ix_payment_transactions_order_id", "order_id"),
        Index("ix_payment_transactions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(30), index=True, default="pending"
    )  # pending | completed | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
