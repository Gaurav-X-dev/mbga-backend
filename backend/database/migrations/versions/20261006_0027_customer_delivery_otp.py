"""Let the owning customer retrieve an active delivery OTP after an app refresh.

The existing hash remains the proof-of-delivery verification source. This second value is
purpose-key encrypted, is exposed only through customer-scoped order responses, and is erased
when the delivery is completed or failed.

Revision ID: 20261006_0027
Revises: 20261005_0026
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0027"
down_revision = "20261005_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_slips",
        sa.Column("confirmation_code_encrypted", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("delivery_slips", "confirmation_code_encrypted")
