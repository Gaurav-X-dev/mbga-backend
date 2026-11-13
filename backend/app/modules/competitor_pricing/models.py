"""Merchant-owned market quotes and append-only price observations."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("merchant_id", "code", name="uq_competitor_merchant_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(7))
    icon_name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))
    depot_line1: Mapped[str | None] = mapped_column(String(255))
    depot_line2: Mapped[str | None] = mapped_column(String(255))
    depot_city: Mapped[str | None] = mapped_column(String(100))
    depot_state: Mapped[str | None] = mapped_column(String(100))
    depot_pincode: Mapped[str | None] = mapped_column(String(6))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompetitorPrice(Base):
    __tablename__ = "competitor_prices"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "competitor_id",
            "cylinder_type",
            "customer_type",
            "location_pincode",
            name="uq_competitor_price_dimensions",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id"))
    cylinder_type: Mapped[str] = mapped_column(String(40))
    customer_type: Mapped[str] = mapped_column(String(40))
    location_pincode: Mapped[str] = mapped_column(String(6))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    old_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(160))
    updated_by_role: Mapped[str] = mapped_column(String(60))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompetitorPriceChangeLog(Base):
    # Initial observations are retained too, so a trend can start before the first change.
    __tablename__ = "competitor_price_change_logs"
    __table_args__ = (
        Index("ix_competitor_log_scope_time", "merchant_id", "cylinder_type", "created_at"),
        Index(
            "ix_competitor_log_market_recorded",
            "merchant_id",
            "customer_type",
            "cylinder_type",
            "location_pincode",
            "created_at",
        ),
        Index(
            "ix_competitor_log_segment_recorded",
            "merchant_id",
            "customer_type",
            "cylinder_type",
            "created_at",
        ),
        Index(
            "ix_competitor_log_effective",
            "merchant_id",
            "cylinder_type",
            "location_pincode",
            "customer_type",
            "effective_date",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    competitor_id: Mapped[str] = mapped_column(String(36))
    competitor_name: Mapped[str] = mapped_column(String(160))
    cylinder_type: Mapped[str] = mapped_column(String(40))
    customer_type: Mapped[str | None] = mapped_column(String(40))
    location_pincode: Mapped[str | None] = mapped_column(String(6))
    old_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    new_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    changed_by_user_id: Mapped[str] = mapped_column(String(36))
    changed_by_user_name: Mapped[str] = mapped_column(String(160))
    changed_by_user_role: Mapped[str] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
