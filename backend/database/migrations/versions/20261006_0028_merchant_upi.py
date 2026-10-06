"""Persist the merchant UPI handle used by the delivery QR endpoint.

The model and QR service already use these fields. This migration closes the schema gap so a
clean database and an existing deployment both match that code. Column checks keep the upgrade
safe for servers where the fields were added manually during the earlier QR rollout.

Revision ID: 20261006_0028
Revises: 20261006_0027
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0028"
down_revision = "20261006_0027"
branch_labels = None
depends_on = None


def _merchant_columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("merchants")}


def upgrade() -> None:
    columns = _merchant_columns()
    if "upi_id" not in columns:
        op.add_column("merchants", sa.Column("upi_id", sa.String(length=120), nullable=True))
    if "upi_payee_name" not in columns:
        op.add_column(
            "merchants",
            sa.Column("upi_payee_name", sa.String(length=160), nullable=True),
        )


def downgrade() -> None:
    columns = _merchant_columns()
    if "upi_payee_name" in columns:
        op.drop_column("merchants", "upi_payee_name")
    if "upi_id" in columns:
        op.drop_column("merchants", "upi_id")
