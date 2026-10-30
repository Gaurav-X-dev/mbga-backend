"""Persistence used only by the Delivery V2 payment split contract."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class DeliveryPaymentBreakdownV2(Base):
    __tablename__ = "delivery_payment_breakdowns_v2"
    __table_args__ = (
        Index("ix_delivery_payment_breakdowns_v2_merchant", "merchant_id", "created_at"),
        Index("ix_delivery_payment_breakdowns_v2_driver", "driver_user_id", "created_at"),
    )

    delivery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    driver_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_collected: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cash_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    upi_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payable_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pending_balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    proof_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proof_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    qr_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qr_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
