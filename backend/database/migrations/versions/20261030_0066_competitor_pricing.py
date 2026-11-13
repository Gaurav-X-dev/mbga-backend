"""Competitor pricing observations, surveys, and merchant directory."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0066"
down_revision = "20261029_0065"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "competitors",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(length=36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), primary_key=False, nullable=False),
        sa.Column("code", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("color", sa.String(length=7), primary_key=False, nullable=False),
        sa.Column("icon_name", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=10), primary_key=False, nullable=False),
        sa.Column("notes", sa.Text(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("merchant_id", "code", name="uq_competitor_merchant_code"),
    )
    op.create_index("ix_competitors_merchant_id", "competitors", ["merchant_id"])
    op.create_table(
        "competitor_prices",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(length=36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "competitor_id",
            sa.String(length=36),
            sa.ForeignKey("competitors.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("cylinder_type", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("customer_type", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("location_pincode", sa.String(length=6), primary_key=False, nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), primary_key=False, nullable=False),
        sa.Column(
            "old_price", sa.Numeric(precision=10, scale=2), primary_key=False, nullable=False
        ),
        sa.Column("effective_date", sa.Date(), primary_key=False, nullable=False),
        sa.Column("notes", sa.Text(), primary_key=False, nullable=True),
        sa.Column("updated_by", sa.String(length=160), primary_key=False, nullable=False),
        sa.Column("updated_by_role", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint(
            "merchant_id",
            "competitor_id",
            "cylinder_type",
            "customer_type",
            "location_pincode",
            name="uq_competitor_price_dimensions",
        ),
    )
    op.create_index("ix_competitor_prices_merchant_id", "competitor_prices", ["merchant_id"])
    op.create_table(
        "competitor_price_change_logs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(length=36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("competitor_id", sa.String(length=36), primary_key=False, nullable=False),
        sa.Column("competitor_name", sa.String(length=160), primary_key=False, nullable=False),
        sa.Column("cylinder_type", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("customer_type", sa.String(length=40), primary_key=False, nullable=True),
        sa.Column("location_pincode", sa.String(length=6), primary_key=False, nullable=True),
        sa.Column(
            "old_price", sa.Numeric(precision=10, scale=2), primary_key=False, nullable=False
        ),
        sa.Column(
            "new_price", sa.Numeric(precision=10, scale=2), primary_key=False, nullable=False
        ),
        sa.Column("effective_date", sa.Date(), primary_key=False, nullable=False),
        sa.Column("changed_by_user_id", sa.String(length=36), primary_key=False, nullable=False),
        sa.Column("changed_by_user_name", sa.String(length=160), primary_key=False, nullable=False),
        sa.Column("changed_by_user_role", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("notes", sa.Text(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_competitor_log_scope_time",
        "competitor_price_change_logs",
        ["merchant_id", "cylinder_type", "created_at"],
    )
    op.create_index(
        "ix_competitor_price_change_logs_merchant_id",
        "competitor_price_change_logs",
        ["merchant_id"],
    )


def downgrade():
    op.drop_table("competitor_price_change_logs")
    op.drop_table("competitor_prices")
    op.drop_table("competitors")
