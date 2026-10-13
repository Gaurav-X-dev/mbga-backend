"""Record the money the driver collects at the gate.

The Delivery App has always sent a payment block when the driver confirms his counts - mode,
amount, what is still pending - and the backend has always thrown it away. No `payments` row was
written, so `invoices.paid_amount` stayed at zero however much cash the driver came back with,
every delivery receipt said "cash" because there was nothing to read, and a customer's balance
counted only what the office had typed in by hand. The agency could not answer the one question
the whole module exists for: how much came in today.

The figures land here first rather than going straight to `payments`, because the driver states
them in one request and they are banked in another - the invoice they pay against is not raised
until the customer's code completes the handover. The slip is where the other figure stated in
that first request already waits, `delivered_quantity`, and for the same reason.

Null throughout means no money was taken at the gate: a customer paying later, or a slip the
office confirmed itself. That is an ordinary outcome, not a missing value, so there is no
default and no backfill - a slip from before today genuinely has no driver-collected payment.

Revision ID: 20261007_0030
Revises: 20261006_0029
"""

import sqlalchemy as sa
from alembic import op

revision = "20261007_0030"
down_revision = "20261006_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_slips", sa.Column("payment_mode", sa.String(10), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_amount", sa.BigInteger(), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_reference", sa.String(80), nullable=True))
    op.add_column(
        "delivery_slips", sa.Column("payment_proof_file_id", sa.String(80), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("delivery_slips", "payment_proof_file_id")
    op.drop_column("delivery_slips", "payment_reference")
    op.drop_column("delivery_slips", "payment_amount")
    op.drop_column("delivery_slips", "payment_mode")
