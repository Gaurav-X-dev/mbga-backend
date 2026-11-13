"""Reminder policies and operational state; existing business records remain authoritative."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class ReminderPolicy(Base):
    __tablename__ = "reminder_policies"
    __table_args__ = (UniqueConstraint("scope", "kind", name="uq_reminder_policy_scope_kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(36))  # platform or merchant UUID
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Reminder(Base):
    __tablename__ = "automated_reminders"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_automated_reminder_fingerprint"),
        Index("ix_automated_reminder_scope_status", "merchant_id", "status", "updated_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    kind: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_profiles.id"), nullable=True
    )
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assigned_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    subject: Mapped[str] = mapped_column(String(180))
    context: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerVisit(Base):
    __tablename__ = "customer_visits"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_customer_visit_key"),
        Index("ix_customer_visit_latest", "merchant_id", "customer_id", "visited_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"))
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    verification: Mapped[str] = mapped_column(String(30))
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PricingReview(Base):
    __tablename__ = "pricing_reviews"
    __table_args__ = (Index("ix_pricing_review_period", "merchant_id", "month", "reviewed_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    month: Mapped[str] = mapped_column(String(7))
    user_id: Mapped[str] = mapped_column(String(36))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
