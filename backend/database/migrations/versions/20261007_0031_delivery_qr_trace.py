"""Keep a trace of the UPI QR a driver shows at the gate.

`generate-qr` built a payment link, returned it and forgot it. Nothing was written, so the one
question the office needs answered during reconciliation - "was a QR shown for this delivery,
and for how much?" - had no answer anywhere. That matters more here than it would elsewhere: the
agency collects on a personal VPA with no gateway behind it, so no system ever tells the
platform the money arrived. The QR and the driver's photo of the payment screen are the whole
evidence trail.

Null means no QR was ever generated for the slip, which is every cash delivery.

Revision ID: 20261007_0031
Revises: 20261007_0030
"""

import sqlalchemy as sa
from alembic import op

revision = "20261007_0031"
down_revision = "20261007_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_slips", sa.Column("qr_amount", sa.BigInteger(), nullable=True))
    op.add_column(
        "delivery_slips", sa.Column("qr_generated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("delivery_slips", "qr_generated_at")
    op.drop_column("delivery_slips", "qr_amount")
