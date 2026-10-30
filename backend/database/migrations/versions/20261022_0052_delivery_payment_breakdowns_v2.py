"""Add isolated Delivery V2 cash and UPI payment breakdowns.

Revision ID: 20261022_0052
Revises: 20261022_0051

No V1 table is altered. The V2 row is also the auditable driver-settlement split;
the normal payments ledger receives separate CASH and UPI entries on completion.
"""

import sqlalchemy as sa
from alembic import context, op

revision = "20261022_0052"
down_revision = "20261022_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "delivery_payment_breakdowns_v2" in inspector.get_table_names():
            return
    op.create_table(
        "delivery_payment_breakdowns_v2",
        sa.Column("delivery_id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), nullable=False),
        sa.Column("driver_user_id", sa.String(36), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("split", sa.String(20), nullable=False),
        sa.Column("amount_collected", sa.BigInteger(), nullable=False),
        sa.Column("cash_amount", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("upi_amount", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("payable_amount", sa.BigInteger(), nullable=False),
        sa.Column("pending_balance", sa.BigInteger(), nullable=False),
        sa.Column("proof_url", sa.String(500), nullable=True),
        sa.Column("proof_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qr_amount", sa.BigInteger(), nullable=True),
        sa.Column("qr_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_delivery_payment_breakdowns_v2_merchant",
        "delivery_payment_breakdowns_v2",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "ix_delivery_payment_breakdowns_v2_driver",
        "delivery_payment_breakdowns_v2",
        ["driver_user_id", "created_at"],
    )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_table("delivery_payment_breakdowns_v2")
        return
    inspector = sa.inspect(op.get_bind())
    if "delivery_payment_breakdowns_v2" in inspector.get_table_names():
        op.drop_table("delivery_payment_breakdowns_v2")
