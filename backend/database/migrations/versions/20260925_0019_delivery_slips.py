"""Delivery slips, their lines and the per-merchant slip-number counter.

Additive: three new tables and nothing altered, so this is safe to apply to a running deployment.
`orders.delivery_slip_id` already exists (added with the orders migration, described there as
"filled by the delivery and invoicing slices when they land"), so no column changes either.

No backfill: existing orders have no slip and are none the worse for it. Staff raise slips for
the orders they are about to load, and an order already delivered before this migration is
history that a slip cannot usefully be invented for.

Written to apply on both MariaDB 10.4 (local) and MySQL 8.4 (compose): no generated columns, no
CHECK constraints. The state machine and the "empties cannot exceed cylinders" rule are enforced
in `app/modules/deliveries/`, where a violation comes back as the coded 409 or 422 the app reads.

Revision ID: 20260925_0019
Revises: 20260925_0018
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0019"
down_revision = "20260925_0018"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    _create_slips()
    _create_slip_items()
    _create_number_sequence()


def downgrade() -> None:
    # Tables only, children first. Dropping an index that backs a foreign key fails on MySQL, and
    # these indexes go with their tables anyway.
    op.drop_table("delivery_slip_items")
    op.drop_table("delivery_slips")
    op.drop_table("delivery_number_sequences")


def _create_slips() -> None:
    op.create_table(
        "delivery_slips",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slip_number", sa.String(30), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_mobile", sa.String(20), nullable=True),
        # Where the van is going, copied from the order so the slip keeps saying where the
        # cylinders actually went after the delivery site is edited.
        sa.Column("delivery_site_name", sa.String(160), nullable=False),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("address_city", sa.String(120), nullable=True),
        sa.Column("address_state", sa.String(120), nullable=True),
        sa.Column("address_pincode", sa.String(6), nullable=True),
        sa.Column("items_summary", sa.String(255), nullable=False),
        sa.Column("cylinders_allocated", sa.Integer(), nullable=False),
        sa.Column("vehicle_number", sa.String(20), nullable=False),
        # Nullable and without a foreign key to users: a merchant may run a hired van whose
        # driver has no account, and the slip must still be raisable for it.
        sa.Column("driver_user_id", sa.String(36), nullable=True),
        sa.Column("driver_name", sa.String(160), nullable=False),
        sa.Column("helper_user_id", sa.String(36), nullable=True),
        sa.Column("helper_name", sa.String(160), nullable=True),
        sa.Column("scheduled_date", TIMESTAMP, nullable=False),
        sa.Column("dispatched_at", TIMESTAMP, nullable=True),
        sa.Column("delivered_at", TIMESTAMP, nullable=True),
        sa.Column("empties_collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmation_method", sa.String(20), nullable=False),
        # Hashed, never the code itself: it authorises a handover, and a plain column would be a
        # live shared secret anybody with table access could read off.
        sa.Column("confirmation_code_hash", sa.String(255), nullable=True),
        sa.Column("confirmation_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_name", sa.String(160), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("dispatched_by_name", sa.String(160), nullable=True),
        sa.Column("confirmed_by_name", sa.String(160), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.UniqueConstraint("merchant_id", "slip_number", name="uq_delivery_slips_merchant_number"),
    )
    op.create_index("ix_delivery_slips_slip_number", "delivery_slips", ["slip_number"])
    op.create_index("ix_delivery_slips_merchant_id", "delivery_slips", ["merchant_id"])
    op.create_index("ix_delivery_slips_status", "delivery_slips", ["status"])
    op.create_index("ix_delivery_slips_customer_id", "delivery_slips", ["customer_id"])
    # The dispatch board: this merchant, by status, newest scheduled first.
    op.create_index(
        "ix_delivery_slips_merchant_status_scheduled",
        "delivery_slips",
        ["merchant_id", "status", "scheduled_date"],
    )
    # "Which slip is this order on?" - the order detail screen and invoicing both ask.
    op.create_index("ix_delivery_slips_order", "delivery_slips", ["order_id"])
    # A driver's own jobs on the delivery app.
    op.create_index("ix_delivery_slips_driver_status", "delivery_slips", ["driver_user_id", "status"])


def _create_slip_items() -> None:
    op.create_table(
        "delivery_slip_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slip_id", sa.String(36), sa.ForeignKey("delivery_slips.id"), nullable=False),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("slip_id", "cylinder_type", name="uq_delivery_slip_items_slip_type"),
    )
    op.create_index("ix_delivery_slip_items_slip_id", "delivery_slip_items", ["slip_id"])


def _create_number_sequence() -> None:
    op.create_table(
        "delivery_number_sequences",
        sa.Column("prefix", sa.String(80), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
