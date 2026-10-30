"""Add optional customer delivery coordinates and instructions.

Revision ID: 20261023_0053
Revises: 20261022_0052
"""

import sqlalchemy as sa
from alembic import context, op

revision = "20261023_0053"
down_revision = "20261022_0052"
branch_labels = None
depends_on = None

ADDITIONS = {
    "customer_profiles": (
        sa.Column("address_latitude", sa.Float(), nullable=True),
        sa.Column("address_longitude", sa.Float(), nullable=True),
        sa.Column("delivery_instructions", sa.String(255), nullable=True),
    ),
    "customer_delivery_sites": (
        sa.Column("delivery_instructions", sa.String(255), nullable=True),
    ),
    "orders": (
        sa.Column("delivery_latitude", sa.Float(), nullable=True),
        sa.Column("delivery_longitude", sa.Float(), nullable=True),
        sa.Column("delivery_instructions", sa.String(255), nullable=True),
    ),
}


def upgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    for table, columns in ADDITIONS.items():
        existing = set() if inspector is None else {item["name"] for item in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    for table, columns in reversed(tuple(ADDITIONS.items())):
        existing = None if inspector is None else {item["name"] for item in inspector.get_columns(table)}
        for column in reversed(columns):
            if existing is None or column.name in existing:
                op.drop_column(table, column.name)
