"""Pricing tables: months, entries, and the two immutable change logs.

Money is `DECIMAL(10,2)` throughout, as the spec's data model specifies. The whole-rupee
`int` convention in `app/shared/money` belongs to order and invoice totals and is untouched
by this module - a per-kg markup is exactly the place a paisa can legitimately appear.

`customer_price` is a **stored generated column**, so `bpcl_base_rate + tier_markup` is
computed by the database and a client-sent total can never reach it, whatever writes the row.

Every table here is scoped to a merchant. `pricing_months` carries `merchant_id` directly;
the two customer tables inherit it from the customer profile, which is already merchant-owned
and is looked up through the tenancy check before any of these rows are read or written.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

MONEY = Numeric(10, 2)


class PricingMonth(Base):
    """One merchant's rate card for one calendar month."""

    __tablename__ = "pricing_months"
    __table_args__ = (
        UniqueConstraint("merchant_id", "month", name="uq_pricing_months_merchant_month"),
        Index("ix_pricing_months_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    label: Mapped[str] = mapped_column(String(60))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    # The display name of whoever last changed a rate in this month, matching the
    # `updated_by`/`created_by` actor-field convention the rest of the API follows.
    updated_by: Mapped[str] = mapped_column(String(160))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PricingEntry(Base):
    """One cylinder type at one tier, inside one pricing month."""

    __tablename__ = "pricing_entries"
    __table_args__ = (
        UniqueConstraint("pricing_month_id", "cylinder_type", "tier", name="uq_pricing_entries_month_type_tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pricing_month_id: Mapped[str] = mapped_column(ForeignKey("pricing_months.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))
    tier: Mapped[str] = mapped_column(String(20), server_default="STANDARD")
    bpcl_base_rate: Mapped[Decimal] = mapped_column(MONEY)
    tier_markup: Mapped[Decimal] = mapped_column(MONEY)
    # Server-computed, never written. Reload the row after an update to read it back.
    # Nullable in the DDL only because MariaDB will not take `NOT NULL` on a STORED
    # generated column; both of its inputs are NOT NULL, so a row can never carry a null
    # here. See the note in migration 20260923_0014.
    customer_price: Mapped[Decimal] = mapped_column(
        MONEY, Computed("bpcl_base_rate + tier_markup", persisted=True), nullable=True
    )


class PricingChangeLog(Base):
    """Append-only record of every rate change, mid-month or not.

    Nothing updates or deletes a row here. The old values are copied in rather than joined
    to, so the log still reads correctly after the entry it describes has moved on.
    """

    __tablename__ = "pricing_change_logs"
    __table_args__ = (
        Index("ix_pricing_change_logs_merchant_effective", "merchant_id", "effective_from"),
        Index("ix_pricing_change_logs_month_type", "pricing_month_id", "cylinder_type", "tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Denormalised from the month so the log can be listed for a merchant without a join,
    # and so the tenancy filter on the list endpoint cannot be forgotten.
    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    pricing_month_id: Mapped[str] = mapped_column(ForeignKey("pricing_months.id"))
    cylinder_type: Mapped[str] = mapped_column(String(40))
    tier: Mapped[str] = mapped_column(String(20))
    # Null when this is the first rate the entry ever carried.
    old_bpcl_base_rate: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    old_tier_markup: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    old_customer_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    new_bpcl_base_rate: Mapped[Decimal] = mapped_column(MONEY)
    new_tier_markup: Mapped[Decimal] = mapped_column(MONEY)
    new_customer_price: Mapped[Decimal] = mapped_column(MONEY)
    effective_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[str] = mapped_column(String(36))
    changed_by_name: Mapped[str] = mapped_column(String(160))
    changed_by_role: Mapped[str] = mapped_column(String(60))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerPriceOverride(Base):
    """The price one customer pays for one cylinder type, instead of the tier price.

    At most one row per customer and cylinder type - the unique constraint is what makes
    "the override" a single, unambiguous thing for quoting and billing to read.
    """

    __tablename__ = "customer_price_overrides"
    __table_args__ = (
        UniqueConstraint("customer_id", "cylinder_type", name="uq_customer_price_overrides_customer_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))
    # The final per-cylinder, GST-inclusive price for this customer.
    override_price: Mapped[Decimal] = mapped_column(MONEY)
    effective_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by_user_id: Mapped[str] = mapped_column(String(36))
    set_by_name: Mapped[str] = mapped_column(String(160))
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerPriceOverrideLog(Base):
    """Append-only record of every override set, changed or removed."""

    __tablename__ = "customer_price_override_logs"
    __table_args__ = (
        Index("ix_customer_price_override_logs_customer_type", "customer_id", "cylinder_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(10))
    # Null on the first SET; `new_override_price` is null on REMOVE.
    old_override_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    new_override_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[str] = mapped_column(String(36))
    changed_by_name: Mapped[str] = mapped_column(String(160))
    changed_by_role: Mapped[str] = mapped_column(String(60))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
