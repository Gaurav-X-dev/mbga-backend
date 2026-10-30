"""Add on-duty driver breadcrumb and latest-location storage.

Revision ID: 20261023_0054
Revises: 20261023_0053
"""

import sqlalchemy as sa
from alembic import context, op

revision = "20261023_0054"
down_revision = "20261023_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_columns: set[str] = set()
    existing_tables: set[str] = set()
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        existing_tables = set(inspector.get_table_names())
        if "delivery_profiles" in existing_tables:
            existing_columns = {
                column["name"] for column in inspector.get_columns("delivery_profiles")
            }

    location_columns = (
        ("current_latitude", sa.Numeric(10, 7)),
        ("current_longitude", sa.Numeric(10, 7)),
        ("location_accuracy", sa.Numeric(8, 2)),
        ("last_ping_at", sa.DateTime(timezone=True)),
    )
    for name, column_type in location_columns:
        if context.is_offline_mode() or name not in existing_columns:
            op.add_column("delivery_profiles", sa.Column(name, column_type, nullable=True))

    if not context.is_offline_mode() and "driver_location_logs" in existing_tables:
        return

    op.create_table(
        "driver_location_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("driver_id", sa.String(36), sa.ForeignKey("delivery_profiles.id"), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("accuracy", sa.Numeric(8, 2), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_driver_location_logs_driver_recorded", "driver_location_logs", ["driver_id", "recorded_at"])
    op.create_index("ix_driver_location_logs_merchant_recorded", "driver_location_logs", ["merchant_id", "recorded_at"])


def downgrade() -> None:
    location_columns = ("last_ping_at", "location_accuracy", "current_longitude", "current_latitude")
    if context.is_offline_mode():
        op.drop_table("driver_location_logs")
        for name in location_columns:
            op.drop_column("delivery_profiles", name)
        return

    inspector = sa.inspect(op.get_bind())
    if "driver_location_logs" in inspector.get_table_names():
        op.drop_table("driver_location_logs")
    existing_columns = {column["name"] for column in inspector.get_columns("delivery_profiles")}
    for name in location_columns:
        if name in existing_columns:
            op.drop_column("delivery_profiles", name)
