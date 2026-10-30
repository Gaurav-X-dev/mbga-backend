"""Customer-type runtime policy fields.

Revision ID: 20261015_0046
Revises: 20261015_0045

The column checks intentionally make this migration compatible with installations that
received an early build of 0045 as well as clean installations using the final 0045.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0046"
down_revision = "20261015_0045"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("customer_type_definitions")}


def upgrade() -> None:
    columns = _columns()
    if "code_prefix" not in columns:
        op.add_column(
            "customer_type_definitions",
            sa.Column("code_prefix", sa.String(8), nullable=False, server_default="C"),
        )
    if "requires_delivery_sites" not in columns:
        op.add_column(
            "customer_type_definitions",
            sa.Column("requires_delivery_sites", sa.Boolean(), nullable=False, server_default="0"),
        )
    op.execute(
        "UPDATE customer_type_definitions "
        "SET code_prefix = CASE code WHEN 'RETAIL' THEN 'R' WHEN 'INDUSTRIAL' THEN 'I' ELSE code_prefix END, "
        "requires_delivery_sites = CASE WHEN code = 'INDUSTRIAL' THEN 1 ELSE requires_delivery_sites END"
    )


def downgrade() -> None:
    columns = _columns()
    if "requires_delivery_sites" in columns:
        op.drop_column("customer_type_definitions", "requires_delivery_sites")
    if "code_prefix" in columns:
        op.drop_column("customer_type_definitions", "code_prefix")
