"""create delivery app tables

Revision ID: 20260923_0007
Revises: 20260914_0006
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260923_0007"
down_revision = "20260914_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. orders
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_number", sa.String(length=40), nullable=False, unique=True),
        sa.Column("merchant_id", sa.String(length=36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("customer_profile_id", sa.String(length=36), sa.ForeignKey("customer_profiles.id"), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("customer_phone", sa.String(length=20), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("address_latitude", sa.Float(), nullable=True),
        sa.Column("address_longitude", sa.Float(), nullable=True),
        sa.Column("time_slot_start", sa.String(length=20), nullable=True),
        sa.Column("time_slot_end", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_merchant_status", "orders", ["merchant_id", "status"])
    op.create_index("ix_orders_customer_profile", "orders", ["customer_profile_id"])

    # 2. order_items
    op.create_table(
        "order_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    # 3. deliveries
    op.create_table(
        "deliveries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("driver_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("merchant_id", sa.String(length=36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("delivered_quantity", sa.Integer(), nullable=True),
        sa.Column("empty_collected_quantity", sa.Integer(), nullable=True),
        sa.Column("driver_latitude", sa.Float(), nullable=True),
        sa.Column("driver_longitude", sa.Float(), nullable=True),
        sa.Column("distance_meters_from_destination", sa.Float(), nullable=True),
        sa.Column("customer_otp_hash", sa.String(length=255), nullable=True),
        sa.Column("customer_otp_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deliveries_driver_status", "deliveries", ["driver_user_id", "status"])
    op.create_index("ix_deliveries_driver_date", "deliveries", ["driver_user_id", "created_at"])
    op.create_index("ix_deliveries_order_id", "deliveries", ["order_id"])

    # 4. notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=200), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])

    # 5. payment_methods
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_methods_user_id", "payment_methods", ["user_id"])

    # 6. payment_transactions
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_transactions_user_id", "payment_transactions", ["user_id"])
    op.create_index("ix_payment_transactions_order_id", "payment_transactions", ["order_id"])
    op.create_index("ix_payment_transactions_status", "payment_transactions", ["status"])

    # 7. driver_inventory
    op.create_table(
        "driver_inventory",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("driver_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("merchant_id", sa.String(length=36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("full_cylinder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("empty_cylinder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vehicle_capacity", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_driver_inventory_driver_user_id", "driver_inventory", ["driver_user_id"])

    # 8. delivery_profiles columns
    op.add_column("delivery_profiles", sa.Column("vehicle_number", sa.String(length=50), nullable=True))
    op.add_column("delivery_profiles", sa.Column("on_duty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("delivery_profiles", sa.Column("language_code", sa.String(length=10), nullable=True, server_default="en"))


def downgrade() -> None:
    op.drop_column("delivery_profiles", "language_code")
    op.drop_column("delivery_profiles", "on_duty")
    op.drop_column("delivery_profiles", "vehicle_number")
    op.drop_table("driver_inventory")
    op.drop_table("payment_transactions")
    op.drop_table("payment_methods")
    op.drop_table("notifications")
    op.drop_table("deliveries")
    op.drop_table("order_items")
    op.drop_table("orders")
