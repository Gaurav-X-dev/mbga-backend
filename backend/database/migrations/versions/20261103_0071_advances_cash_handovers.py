"""Customer advances and driver cash handovers; existing balances and receipts remain unchanged."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261103_0071"
down_revision = "20261103_0070"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "finance_settings",
        sa.Column("scope", sa.String(36), primary_key=True, nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "advance_accounts",
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customer_profiles.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "balance >= 0 AND reserved >= 0 AND balance >= reserved", name="ck_advance_nonnegative"
        ),
    )
    op.create_index("ix_advance_accounts_merchant_id", "advance_accounts", ["merchant_id"])
    op.create_table(
        "advance_deposits",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("merchant_id", "reference", name="uq_advance_deposit_reference"),
        sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_advance_deposit_key"),
    )
    op.create_index("ix_advance_deposits_merchant_id", "advance_deposits", ["merchant_id"])
    op.create_index("ix_advance_deposits_customer_id", "advance_deposits", ["customer_id"])
    op.create_table(
        "advance_entries",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("order_id", sa.String(36), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_advance_entry_key"),
        sa.UniqueConstraint("payment_id", name=None),
        sa.UniqueConstraint("merchant_id", "kind", "reference", name="uq_advance_entry_reference"),
    )
    op.create_index(
        "ix_advance_entry_customer_time", "advance_entries", ["customer_id", "created_at"]
    )
    op.create_table(
        "advance_reservations",
        sa.Column(
            "order_id", sa.String(36), sa.ForeignKey("orders.id"), primary_key=True, nullable=False
        ),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("applied_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_advance_reservations_customer_id", "advance_reservations", ["customer_id"])
    op.create_table(
        "cash_custody",
        sa.Column(
            "payment_id",
            sa.String(36),
            sa.ForeignKey("payments.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "driver_id", sa.String(36), sa.ForeignKey("delivery_profiles.id"), nullable=False
        ),
        sa.Column("driver_user_id", sa.String(36), nullable=False),
        sa.Column("driver_name", sa.String(160), nullable=False),
        sa.Column("vehicle_number", sa.String(50), nullable=False),
        sa.Column("invoice_number", sa.String(40), nullable=False),
        sa.Column("cash_amount", sa.BigInteger(), nullable=False),
        sa.Column("received_amount", sa.BigInteger(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cash_custody_driver", "cash_custody", ["merchant_id", "driver_id", "collected_at"]
    )
    op.create_table(
        "cash_handovers",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "driver_id", sa.String(36), sa.ForeignKey("delivery_profiles.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("expected_amount", sa.BigInteger(), nullable=False),
        sa.Column("received_amount", sa.BigInteger(), nullable=True),
        sa.Column("difference", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_cash_handover_key"),
    )
    op.create_index("ix_cash_handovers_driver_id", "cash_handovers", ["driver_id"])
    op.create_index("ix_cash_handovers_merchant_id", "cash_handovers", ["merchant_id"])
    op.create_table(
        "cash_handover_items",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("handover_id", sa.String(36), sa.ForeignKey("cash_handovers.id"), nullable=False),
        sa.Column(
            "payment_id", sa.String(36), sa.ForeignKey("cash_custody.payment_id"), nullable=False
        ),
        sa.Column("expected_amount", sa.BigInteger(), nullable=False),
        sa.Column("received_amount", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("handover_id", "payment_id", name="uq_cash_handover_item"),
    )
    op.create_index("ix_cash_handover_items_payment_id", "cash_handover_items", ["payment_id"])
    op.create_index("ix_cash_handover_items_handover_id", "cash_handover_items", ["handover_id"])
    table = sa.table(
        "finance_settings",
        sa.column("scope", sa.String),
        sa.column("config", sa.Text),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        table,
        [
            {
                "scope": "platform",
                "config": '{"advanceEnabled":false,"autoUseAdvance":true,"allowPartialAdvance":true,"maxDepositAmount":10000000,"handoverEnabled":true,"requireSeparateVerifier":false}',
                "updated_at": datetime(2026, 11, 3, tzinfo=UTC),
            }
        ],
    )


def downgrade():
    # Financial history must never disappear through a routine rollback.
    connection = op.get_bind()
    for name in (
        "advance_entries",
        "advance_deposits",
        "advance_reservations",
        "cash_custody",
        "cash_handovers",
    ):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar():
            raise RuntimeError("Cannot downgrade finance migration while financial records exist.")
    op.drop_table("cash_handover_items")
    op.drop_table("cash_handovers")
    op.drop_table("cash_custody")
    op.drop_table("advance_reservations")
    op.drop_table("advance_entries")
    op.drop_table("advance_deposits")
    op.drop_table("advance_accounts")
    op.drop_table("finance_settings")
