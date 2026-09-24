"""Operational spend tracking: per-merchant expense categories and the expenses filed to them.

Additive: two new tables, nothing existing is touched.

Categories are per-merchant rather than global. A global table would need a nullable
`merchant_id` to mark the system rows, and MySQL treats NULLs as distinct inside a unique
index - so `UNIQUE (merchant_id, code)` would stop protecting against duplicate system
categories. Per-merchant rows keep the constraint meaningful and let one merchant rename a
category without touching anyone else's.

Revision ID: 20260923_0015
Revises: 20260923_0014
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0015"
down_revision = "20260923_0014"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)
MONEY = sa.Numeric(12, 2)


def upgrade() -> None:
    _create_expense_categories()
    _create_expenses()


def downgrade() -> None:
    """Child first, tables only.

    The indexes are not dropped separately: MySQL backs a foreign key with the leftmost
    index covering its column and refuses to drop it while the table stands. Dropping the
    table takes its indexes with it.
    """
    op.drop_table("expenses")
    op.drop_table("expense_categories")


def _create_expense_categories() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False, index=True),
        # Stable machine key (FUEL, VEHICLE_MAINTENANCE). Never changes on a rename, so
        # historical rows and saved filters keep working.
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        # One of the icon keys the app has a drawable for.
        sa.Column("icon", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Deactivated rather than deleted once expenses reference it: out of the picker,
        # still readable in history.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        # False for the seeded starting set, true for one the merchant added.
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.UniqueConstraint("merchant_id", "code", name="uq_expense_categories_merchant_code"),
    )
    op.create_index(
        "ix_expense_categories_merchant_active",
        "expense_categories",
        ["merchant_id", "is_active", "sort_order"],
    )


def _create_expenses() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column(
            "category_id",
            sa.String(36),
            sa.ForeignKey("expense_categories.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        # The day the money was spent, as the operator entered it.
        sa.Column("spent_on", sa.Date(), nullable=False),
        # 'YYYY-MM', derived from spent_on by the service and never sent by a client.
        # Stored rather than computed in the query: the list filters by report period on
        # every load, and MONTH(spent_on) in a WHERE clause cannot use an index.
        sa.Column("period", sa.String(7), nullable=False),
        # The acting user, copied from the session. The name is denormalised so the list
        # still reads correctly after a staff member is renamed or removed.
        sa.Column("recorded_by_user_id", sa.String(36), nullable=False),
        sa.Column("recorded_by_name", sa.String(160), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
    # The list screen's default query: this merchant, this period, newest first.
    op.create_index("ix_expenses_merchant_period_date", "expenses", ["merchant_id", "period", "spent_on"])
    op.create_index("ix_expenses_merchant_category", "expenses", ["merchant_id", "category_id"])
    op.create_index("ix_expenses_merchant_date", "expenses", ["merchant_id", "spent_on"])
