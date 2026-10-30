"""Add UPI presentation channel and receipt evidence to V2 collections.

Revision ID: 20261026_0057
Revises: 20261026_0056
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20261026_0057"
down_revision = "20261026_0056"
branch_labels = None
depends_on = None

_MICROS = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    op.add_column(
        "payment_collections",
        sa.Column("payment_channel", sa.String(20), nullable=False, server_default="QR"),
    )
    op.add_column(
        "payment_collections", sa.Column("upi_id_snapshot", sa.String(120), nullable=True)
    )
    op.add_column(
        "payment_collections", sa.Column("payee_name_snapshot", sa.String(160), nullable=True)
    )
    op.add_column(
        "payment_collections", sa.Column("receipt_storage_key", sa.String(500), nullable=True)
    )
    op.add_column(
        "payment_collections", sa.Column("receipt_content_type", sa.String(80), nullable=True)
    )
    op.add_column("payment_collections", sa.Column("receipt_uploaded_at", _MICROS, nullable=True))
    op.execute(
        "UPDATE payment_collections pc JOIN merchants m ON m.id = pc.merchant_id "
        "SET pc.upi_id_snapshot = m.upi_id, pc.payee_name_snapshot = m.upi_payee_name "
        "WHERE pc.upi_id_snapshot IS NULL"
    )


def downgrade() -> None:
    for column in (
        "receipt_uploaded_at",
        "receipt_content_type",
        "receipt_storage_key",
        "payee_name_snapshot",
        "upi_id_snapshot",
        "payment_channel",
    ):
        op.drop_column("payment_collections", column)
