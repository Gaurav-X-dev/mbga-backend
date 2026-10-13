"""Take the payment-proof photo back off a delivery.

It was built on the reasoning that a UPI collection needs evidence, since no gateway tells the
platform whether the money arrived. The Delivery App has no field for it and is not going to
get one: the driver is at a gate with one hand on a cylinder, and the evidence that is actually
kept is the QR the platform itself raised - `qr_amount` and `qr_generated_at` - which the office
matches against the bank statement.

A column nothing writes is a column the next person has to work out the meaning of. It never
held a value: the endpoint that set it was removed before any delivery used it.

Revision ID: 20261008_0038
Revises: 20261008_0037
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0038"
down_revision = "20261008_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("delivery_slips", "payment_proof_file_id")


def downgrade() -> None:
    op.add_column(
        "delivery_slips", sa.Column("payment_proof_file_id", sa.String(80), nullable=True)
    )
