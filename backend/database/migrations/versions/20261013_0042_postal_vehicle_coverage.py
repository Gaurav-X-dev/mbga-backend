"""Postal directory and merchant vehicle coverage.

Revision ID: 20261013_0042
Revises: 20261012_0041
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0042"
down_revision = "20261012_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "postal_locations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pincode", sa.String(6), nullable=False),
        sa.Column("office_name", sa.String(160), nullable=False),
        sa.Column("office_type", sa.String(40), nullable=True),
        sa.Column("delivery_available", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("district_name", sa.String(120), nullable=False),
        sa.Column("state_name", sa.String(120), nullable=False),
        sa.Column("circle_name", sa.String(120), nullable=True),
        sa.Column("region_name", sa.String(120), nullable=True),
        sa.Column("division_name", sa.String(120), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("pincode", "office_name", name="uq_postal_locations_pincode_office"),
    )
    op.create_index(
        "ix_postal_locations_pincode_active", "postal_locations", ["pincode", "is_active"]
    )
    op.create_index(
        "ix_postal_locations_state_district", "postal_locations", ["state_name", "district_name"]
    )
    op.create_table(
        "vehicle_pincode_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("vehicle_id", sa.String(36), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("pincode", sa.String(6), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("vehicle_id", "pincode", name="uq_vehicle_pincode_mapping"),
    )
    op.create_index(
        "ix_vehicle_pincode_mappings_merchant_id", "vehicle_pincode_mappings", ["merchant_id"]
    )
    op.create_index(
        "ix_vehicle_pincode_mappings_vehicle_id", "vehicle_pincode_mappings", ["vehicle_id"]
    )
    op.create_index(
        "ix_vehicle_pincode_merchant_pin",
        "vehicle_pincode_mappings",
        ["merchant_id", "pincode", "is_active"],
    )


def downgrade() -> None:
    op.drop_table("vehicle_pincode_mappings")
    op.drop_table("postal_locations")
