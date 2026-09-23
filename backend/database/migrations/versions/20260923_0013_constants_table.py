"""Key/value reference data the apps read.

Additive: one new table, nothing existing is touched.

Revision ID: 20260923_0013
Revises: 20260921_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0013"
down_revision = "20260921_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "constants",
        sa.Column("id", sa.String(36), primary_key=True),
        # What the app sends back to the API, e.g. "RETAIL".
        sa.Column("const_key", sa.String(100), nullable=False),
        # What the app shows the user, e.g. "Retail".
        sa.Column("const_value", sa.String(255), nullable=False),
        # Which dropdown the row belongs to.
        sa.Column("const_group", sa.String(50), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # A key is the app's handle for a row, so two rows may not share one.
        sa.UniqueConstraint("const_key", name="uq_constants_const_key"),
    )
    op.create_index("ix_constants_group", "constants", ["const_group"])


def downgrade() -> None:
    op.drop_index("ix_constants_group", table_name="constants")
    op.drop_table("constants")
