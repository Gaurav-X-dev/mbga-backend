from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class CreditSettingsAudit(Base):
    __tablename__ = "credit_settings_audit"
    __table_args__ = (Index("ix_credit_audit_customer_created", "customer_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    old_enabled: Mapped[bool] = mapped_column(Boolean)
    new_enabled: Mapped[bool] = mapped_column(Boolean)
    old_limit: Mapped[int] = mapped_column(BigInteger)
    new_limit: Mapped[int] = mapped_column(BigInteger)
    old_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_by_user_id: Mapped[str] = mapped_column(String(36))
    changed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CreditOverrideAudit(Base):
    __tablename__ = "credit_override_audit"
    __table_args__ = (Index("ix_credit_override_customer_created", "customer_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    used_credit: Mapped[int] = mapped_column(BigInteger)
    credit_limit: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    approved_by_user_id: Mapped[str] = mapped_column(String(36))
    approved_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CreditReminderState(Base):
    __tablename__ = "credit_reminder_states"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), primary_key=True)
    cycle_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
