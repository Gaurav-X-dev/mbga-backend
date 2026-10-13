"""Composite indexes for tenant-scoped report ranges.

Revision ID: 20261009_0039
Revises: 20261008_0038
"""

from alembic import op

revision = "20261009_0039"
down_revision = "20261008_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_delivery_slips_merchant_delivered",
        "delivery_slips",
        ["merchant_id", "delivered_at"],
    )
    op.create_index(
        "ix_payments_merchant_reconciliation_paid",
        "payments",
        ["merchant_id", "reconciliation_status", "paid_at", "mode"],
    )
    op.create_index(
        "ix_expenses_merchant_category_date",
        "expenses",
        ["merchant_id", "category_id", "spent_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_expenses_merchant_category_date", table_name="expenses")
    op.drop_index("ix_payments_merchant_reconciliation_paid", table_name="payments")
    op.drop_index("ix_delivery_slips_merchant_delivered", table_name="delivery_slips")
