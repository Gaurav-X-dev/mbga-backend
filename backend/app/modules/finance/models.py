"""Customer-owned advances and driver cash custody, separate from sales revenue."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class FinanceSettings(Base):
    __tablename__ = "finance_settings"
    scope: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdvanceAccount(Base):
    __tablename__ = "advance_accounts"
    __table_args__ = (
        CheckConstraint(
            "balance >= 0 AND reserved >= 0 AND balance >= reserved", name="ck_advance_nonnegative"
        ),
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdvanceDeposit(Base):
    __tablename__ = "advance_deposits"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_advance_deposit_key"),
        UniqueConstraint("merchant_id", "reference", name="uq_advance_deposit_reference"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_by: Mapped[str] = mapped_column(String(36))
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdvanceEntry(Base):
    __tablename__ = "advance_entries"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_advance_entry_key"),
        UniqueConstraint("merchant_id", "kind", "reference", name="uq_advance_entry_reference"),
        Index("ix_advance_entry_customer_time", "customer_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)  # signed; held amounts are separate
    balance_after: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True, unique=True
    )
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdvanceReservation(Base):
    __tablename__ = "advance_reservations"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    applied_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CashCustody(Base):
    __tablename__ = "cash_custody"
    __table_args__ = (Index("ix_cash_custody_driver", "merchant_id", "driver_id", "collected_at"),)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    driver_id: Mapped[str] = mapped_column(ForeignKey("delivery_profiles.id"))
    driver_user_id: Mapped[str] = mapped_column(String(36))
    driver_name: Mapped[str] = mapped_column(String(160))
    vehicle_number: Mapped[str] = mapped_column(String(50))
    invoice_number: Mapped[str] = mapped_column(String(40))
    cash_amount: Mapped[int] = mapped_column(BigInteger)
    received_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CashHandover(Base):
    __tablename__ = "cash_handovers"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_cash_handover_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("delivery_profiles.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    expected_amount: Mapped[int] = mapped_column(BigInteger)
    received_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    difference: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CashHandoverItem(Base):
    __tablename__ = "cash_handover_items"
    __table_args__ = (UniqueConstraint("handover_id", "payment_id", name="uq_cash_handover_item"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    handover_id: Mapped[str] = mapped_column(ForeignKey("cash_handovers.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("cash_custody.payment_id"), index=True)
    expected_amount: Mapped[int] = mapped_column(BigInteger)
    received_amount: Mapped[int] = mapped_column(BigInteger, default=0)
