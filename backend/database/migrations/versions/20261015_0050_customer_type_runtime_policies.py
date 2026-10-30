"""Make default customer type and invoice policy catalogue-driven.

Revision ID: 20261015_0050
Revises: 20261015_0049
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0050"
down_revision = "20261015_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("customer_type_definitions")}
    if "requires_gst_invoice" not in columns:
        op.add_column("customer_type_definitions", sa.Column(
            "requires_gst_invoice", sa.Boolean(), nullable=False, server_default="0"
        ))
    if "is_default" not in columns:
        op.add_column("customer_type_definitions", sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default="0"
        ))
    op.execute(
        "UPDATE customer_type_definitions SET "
        "requires_gst_invoice = CASE WHEN code = 'INDUSTRIAL' THEN 1 ELSE requires_gst_invoice END, "
        "is_default = CASE WHEN code = 'RETAIL' THEN 1 ELSE 0 END"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("customer_type_definitions")}
    if "is_default" in columns:
        op.drop_column("customer_type_definitions", "is_default")
    if "requires_gst_invoice" in columns:
        op.drop_column("customer_type_definitions", "requires_gst_invoice")
