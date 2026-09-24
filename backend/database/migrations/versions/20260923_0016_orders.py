"""Orders, their lines, the status trail and the per-merchant order-number counter.

Additive: four new tables, nothing existing is touched.

Money is BIGINT whole rupees (spec §1) rather than the DECIMAL(10,2) the pricing tables use.
A per-kg markup can legitimately hold paise; an order total cannot, so the rounding happens
once at the quoting boundary and what lands here is already an integer.

Prices are copied onto the line rather than joined to the price card. A card changes
mid-month by design, and an order has to keep the price it was placed at or every historical
total silently rewrites itself the next time a rate moves.

Revision ID: 20260923_0016
Revises: 20260923_0015
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0016"
down_revision = "20260923_0015"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)
MONEY = sa.BigInteger()


def upgrade() -> None:
    _create_order_number_sequences()
    _create_orders()
    _create_order_items()
    _create_order_status_history()


def downgrade() -> None:
    """Children before parents, tables only.

    The indexes are not dropped separately: MySQL backs a foreign key with the leftmost
    index covering its column and refuses to drop it while the table stands.
    """
    op.drop_table("order_status_history")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("order_number_sequences")


def _create_order_number_sequences() -> None:
    op.create_table(
        "order_number_sequences",
        # 'ORD-<merchant_id>-2609'. One row per merchant per month, locked with
        # SELECT ... FOR UPDATE while it is incremented.
        sa.Column("prefix", sa.String(80), primary_key=True),
        sa.Column("next_value", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )


def _create_orders() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.String(36), primary_key=True),
        # Readable and sequential per merchant. Never used for authorisation - it is
        # guessable by design, so lookups still apply the tenancy filter.
        sa.Column("order_number", sa.String(30), nullable=False, index=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False, index=True),
        # Denormalised so the list renders without a join and still reads correctly after a
        # customer is renamed. Also what the search filter matches.
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_type", sa.String(40), nullable=False),
        sa.Column("order_mode", sa.String(10), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("delivery_site_id", sa.String(36), nullable=True),
        sa.Column("delivery_site_name", sa.String(160), nullable=False),
        # The address is copied, not joined: moving a site must not rewrite where a past
        # order was actually delivered.
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("address_city", sa.String(120), nullable=True),
        sa.Column("address_state", sa.String(120), nullable=True),
        sa.Column("address_pincode", sa.String(6), nullable=True),
        sa.Column("total_cylinders", sa.Integer(), nullable=False),
        sa.Column("items_summary", sa.String(255), nullable=False),
        # GST-inclusive total; subtotal and gst_amount are broken out of it (spec §18.1).
        sa.Column("total_amount", MONEY, nullable=False),
        sa.Column("subtotal", MONEY, nullable=False),
        sa.Column("gst_amount", MONEY, nullable=False),
        sa.Column("gst_percent", sa.Integer(), nullable=False),
        sa.Column("pricing_month_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("placed_at", TIMESTAMP, nullable=False),
        # The cut-off exactly as evaluated at placement, so an order opened a week later
        # still shows the promise that was made.
        sa.Column("cutoff_time", sa.String(5), nullable=False),
        sa.Column("within_cutoff", sa.Boolean(), nullable=False),
        sa.Column("scheduled_delivery_date", TIMESTAMP, nullable=False),
        sa.Column("cutoff_message", sa.String(255), nullable=False),
        sa.Column("delivery_slot", sa.String(40), nullable=True),
        sa.Column("created_by", sa.String(160), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        # Filled by the delivery and invoicing slices when they land.
        sa.Column("delivery_slip_id", sa.String(36), nullable=True),
        sa.Column("invoice_id", sa.String(36), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.UniqueConstraint("merchant_id", "order_number", name="uq_orders_merchant_number"),
    )
    # The Orders tab: this merchant, newest first, optionally filtered by status.
    op.create_index("ix_orders_merchant_status_placed", "orders", ["merchant_id", "status", "placed_at"])
    # The customer app's own list, and the customer-detail history on the merchant side.
    op.create_index("ix_orders_customer_placed", "orders", ["customer_id", "placed_at"])


def _create_order_items() -> None:
    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        # GST-inclusive, per cylinder, as resolved for this customer at placement.
        sa.Column("unit_price", MONEY, nullable=False),
        sa.Column("line_total", MONEY, nullable=False),
        # True when a per-customer override priced the line rather than the tier card, so a
        # disputed invoice can be explained without replaying the price history.
        sa.Column("price_overridden", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Duplicate lines are merged before insert, so one type appears once per order.
        sa.UniqueConstraint("order_id", "cylinder_type", name="uq_order_items_order_type"),
    )


def _create_order_status_history() -> None:
    op.create_table(
        "order_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        # Display name of whoever moved it, copied from the session.
        sa.Column("changed_by_name", sa.String(160), nullable=True),
        sa.Column("changed_by_user_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_order_status_history_order_at", "order_status_history", ["order_id", "changed_at"])
