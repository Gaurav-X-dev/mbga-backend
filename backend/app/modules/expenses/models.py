"""Expense tables: the merchant's categories and the spend rows filed against them.

Both are scoped to a merchant. Categories are per-merchant rather than global so one
merchant renaming "Salary" to "Wages" cannot change what another merchant sees, and so
`UNIQUE (merchant_id, code)` is a real constraint - a global table would need a nullable
`merchant_id`, and MySQL treats NULLs as distinct in a unique index, which would let
duplicate system categories in.

`period` is stored on the row rather than derived in SQL. The list screen filters by report
period on every load; `MONTH(spent_on)` in a WHERE clause cannot use an index, a stored
`YYYY-MM` column can. It is written by the service from `spent_on` and never by a client.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

MONEY = Numeric(12, 2)


class ExpenseCategory(Base):
    """One spend bucket, as this merchant has it configured."""

    __tablename__ = "expense_categories"
    __table_args__ = (
        UniqueConstraint("merchant_id", "code", name="uq_expense_categories_merchant_code"),
        Index("ix_expense_categories_merchant_active", "merchant_id", "is_active", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    # Stable machine key (FUEL, VEHICLE_MAINTENANCE). The app may filter on it; the label
    # is what it displays. Renaming a category never changes its code, so a saved filter
    # and every historical row keep working.
    code: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(60))
    # One of `ExpenseIcon`, so the app always has a drawable for it.
    icon: Mapped[str] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Deactivated rather than deleted once expenses reference it: the picker hides it, the
    # history still renders it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # False for the seeded starting set, so the seeder can tell its own rows from the
    # merchant's and never "repair" a category the merchant made.
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Expense(Base):
    """One recorded spend."""

    __tablename__ = "expenses"
    __table_args__ = (
        # The list screen's default query: this merchant, this report period, newest first.
        Index("ix_expenses_merchant_period_date", "merchant_id", "period", "spent_on"),
        Index("ix_expenses_merchant_category", "merchant_id", "category_id"),
        Index("ix_expenses_merchant_date", "merchant_id", "spent_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("expense_categories.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The day the money was spent, as the operator entered it.
    spent_on: Mapped[date] = mapped_column(Date)
    # 'YYYY-MM', derived from `spent_on` by the service. Indexed for the period filter.
    period: Mapped[str] = mapped_column(String(7))
    # Who filed it. Taken from the session, never from the request body, and the name is
    # copied so the list still reads correctly after a staff member is renamed or removed.
    recorded_by_user_id: Mapped[str] = mapped_column(String(36))
    recorded_by_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
