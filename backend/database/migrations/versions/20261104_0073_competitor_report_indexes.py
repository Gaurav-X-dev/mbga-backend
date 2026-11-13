"""Indexes for recorded-date and effective-date competitor market reads."""

from alembic import op

revision = "20261104_0073"
down_revision = "20261104_0072"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_competitor_log_market_recorded": [
        "merchant_id",
        "customer_type",
        "cylinder_type",
        "location_pincode",
        "created_at",
    ],
    "ix_competitor_log_segment_recorded": [
        "merchant_id",
        "customer_type",
        "cylinder_type",
        "created_at",
    ],
    "ix_competitor_log_effective": [
        "merchant_id",
        "cylinder_type",
        "location_pincode",
        "customer_type",
        "effective_date",
    ],
}


def upgrade():
    for name, columns in INDEXES.items():
        op.create_index(name, "competitor_price_change_logs", columns)


def downgrade():
    for name in reversed(INDEXES):
        op.drop_index(name, table_name="competitor_price_change_logs")
