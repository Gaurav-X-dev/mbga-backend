"""Configurable arrival radius: 300m default with agency-specific overrides."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_0065"
down_revision = "20261028_0064"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "platform_settings",
        sa.Column("delivery_radius_metres", sa.Integer(), nullable=False, server_default="300"),
    )
    op.add_column("merchants", sa.Column("delivery_radius_metres", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("merchants", "delivery_radius_metres")
    op.drop_column("platform_settings", "delivery_radius_metres")
