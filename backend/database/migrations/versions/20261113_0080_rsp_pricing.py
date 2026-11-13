"""Replace base-plus-markup pricing with Plant EX-MI and RSP prices.

Revision ID: 20261113_0080
Revises: 20261113_0079
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0080"
down_revision = "20261113_0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve today's selling price before the second input changes meaning from markup to RSP.
    op.execute("UPDATE pricing_entries SET tier_markup = bpcl_base_rate + tier_markup")
    op.execute("ALTER TABLE pricing_entries DROP COLUMN customer_price")
    op.execute(
        "ALTER TABLE pricing_entries ADD COLUMN customer_price DECIMAL(10,2) "
        "GENERATED ALWAYS AS (tier_markup) STORED"
    )
    # Historical log rows now use the legacy columns as Plant EX-MI/RSP storage too.
    op.execute(
        "UPDATE pricing_change_logs SET old_tier_markup = old_customer_price, "
        "new_tier_markup = new_customer_price"
    )
    for name, type_ in (
        ("billing_name", sa.String(160)),
        ("billing_gstin", sa.String(30)),
        ("billing_contact", sa.String(20)),
        ("billing_address_line1", sa.String(255)),
        ("billing_address_line2", sa.String(255)),
        ("billing_city", sa.String(120)),
        ("billing_state", sa.String(120)),
        ("billing_pincode", sa.String(12)),
        ("ship_to_contact_name", sa.String(160)),
        ("ship_to_contact_mobile", sa.String(20)),
    ):
        op.add_column("orders", sa.Column(name, type_, nullable=True))
    op.execute(
        "UPDATE orders o JOIN customer_profiles c ON c.id=o.customer_id SET "
        "o.billing_name=COALESCE(c.name,c.owner_name,o.customer_name), "
        "o.billing_gstin=c.gst_number, o.billing_contact=c.mobile_number, "
        "o.billing_address_line1=c.address_line1, o.billing_address_line2=c.address_line2, "
        "o.billing_city=c.address_city, o.billing_state=c.address_state, "
        "o.billing_pincode=c.address_pincode"
    )
    op.add_column("expenses", sa.Column("start_odometer", sa.Numeric(12, 2), nullable=True))
    op.add_column("expenses", sa.Column("end_odometer", sa.Numeric(12, 2), nullable=True))
    op.alter_column("order_items", "unit_price", existing_type=sa.BigInteger(), type_=sa.Numeric(12, 2), nullable=False)


def downgrade() -> None:
    op.alter_column("order_items", "unit_price", existing_type=sa.Numeric(12, 2), type_=sa.BigInteger(), nullable=False)
    op.drop_column("expenses", "end_odometer")
    op.drop_column("expenses", "start_odometer")
    for name in (
        "ship_to_contact_mobile", "ship_to_contact_name", "billing_pincode",
        "billing_state", "billing_city", "billing_address_line2", "billing_address_line1",
        "billing_contact", "billing_gstin", "billing_name",
    ):
        op.drop_column("orders", name)
    op.execute("ALTER TABLE pricing_entries DROP COLUMN customer_price")
    op.execute(
        "UPDATE pricing_entries SET tier_markup = GREATEST(tier_markup - bpcl_base_rate, 0)"
    )
    op.execute(
        "ALTER TABLE pricing_entries ADD COLUMN customer_price DECIMAL(10,2) "
        "GENERATED ALWAYS AS (bpcl_base_rate + tier_markup) STORED"
    )
