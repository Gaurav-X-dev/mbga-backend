"""Merchant-scoped customer reporting groups; no financial balances are copied."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_0068"
down_revision = "20261102_0067"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_report_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "name", name="uq_customer_report_group_name"),
    )
    op.create_index(
        "ix_customer_report_groups_merchant_id", "customer_report_groups", ["merchant_id"]
    )
    op.create_table(
        "customer_report_memberships",
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), primary_key=True
        ),
        sa.Column(
            "group_id", sa.String(36), sa.ForeignKey("customer_report_groups.id"), nullable=False
        ),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_customer_report_memberships_group_id", "customer_report_memberships", ["group_id"]
    )


def downgrade():
    op.drop_table("customer_report_memberships")
    op.drop_table("customer_report_groups")
