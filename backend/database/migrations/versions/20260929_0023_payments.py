"""Invoices and payments (spec §3.14, §3.15, §12).

Three new tables. Nothing existing is altered, so this runs against a live database without a
backfill and without a window.

* `invoices` - what a customer owes, one per delivered order. `order_id` is UNIQUE, and that
  constraint is the guard against double-billing rather than a check in the service: a check
  that reads then writes has a window between the two, and two confirmations arriving together
  would both pass it.

* `payments` - each act of collecting. Several may land on one invoice, so the invoice's
  `paid_amount` is a summary of these rows and never a figure typed in by hand.

* `payment_number_sequences` - the per-merchant counters behind `MBGA/INV/0144` and `PAY-0211`.
  Neither resets: an invoice run that restarted monthly would produce two `MBGA/INV/0001` in one
  financial year, which is the one thing an invoice number must never do.

`issued_at` and `paid_at` are `DATETIME(6)`. Both carry ordering that means something - "newest
payment first", "last payment at" - and plain MySQL DATETIME keeps only whole seconds, so two
payments recorded in the same second would come back in arbitrary order.

Money is BIGINT whole rupees, as everywhere else on the platform. No CHECK constraints and no
generated columns: MariaDB 10.4 is the local database and does not take them the way MySQL 8
does, so the invariants live in the service and in its tests.

Revision ID: 20260929_0023
Revises: 20260928_0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260929_0023"
down_revision = "20260928_0022"
branch_labels = None
depends_on = None

#: Ordering depends on these, so they keep microseconds.
MICROS = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("invoice_number", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_number", sa.String(length=30), nullable=False),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("customer_profiles.id"), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("gst_percent", sa.Integer(), nullable=False),
        sa.Column("gst_amount", sa.BigInteger(), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("paid_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issued_at", MICROS, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_gst_invoice", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One invoice per order - the guard against billing a customer twice for one delivery.
        sa.UniqueConstraint("order_id", name="uq_invoices_order"),
        sa.UniqueConstraint("merchant_id", "invoice_number", name="uq_invoices_merchant_number"),
    )
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_customer_issued", "invoices", ["customer_id", "issued_at"])
    op.create_index("ix_invoices_merchant_status", "invoices", ["merchant_id", "status"])
    op.create_index("ix_invoices_merchant_due", "invoices", ["merchant_id", "due_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("payment_number", sa.String(length=30), nullable=False),
        sa.Column("merchant_id", sa.String(length=36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("invoice_number", sa.String(length=40), nullable=False),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("customer_profiles.id"), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("invoice_amount", sa.BigInteger(), nullable=False),
        sa.Column("amount_collected", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("paid_at", MICROS, nullable=False),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column("reconciliation_status", sa.String(length=20), nullable=False),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_by_name", sa.String(length=160), nullable=True),
        sa.Column("collected_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("collected_by_name", sa.String(length=160), nullable=True),
        # Frozen at the moment of collection, so a receipt keeps showing the balance it showed.
        sa.Column("customer_running_balance", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "payment_number", name="uq_payments_merchant_number"),
    )
    op.create_index("ix_payments_payment_number", "payments", ["payment_number"])
    op.create_index("ix_payments_paid_at", "payments", ["paid_at"])
    op.create_index("ix_payments_merchant_paid_at", "payments", ["merchant_id", "paid_at"])
    op.create_index(
        "ix_payments_merchant_reconciliation", "payments", ["merchant_id", "reconciliation_status"]
    )
    op.create_index("ix_payments_customer_paid_at", "payments", ["customer_id", "paid_at"])
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])

    op.create_table(
        "payment_number_sequences",
        sa.Column("prefix", sa.String(length=120), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # Tables only. MySQL drops a table's indexes with it, and dropping them first fails anyway:
    # an index backing a foreign key cannot be removed while the constraint still needs it.
    # Order matters - payments points at invoices.
    op.drop_table("payment_number_sequences")
    op.drop_table("payments")
    op.drop_table("invoices")
