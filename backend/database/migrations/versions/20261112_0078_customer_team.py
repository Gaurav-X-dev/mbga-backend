"""Separate owner-managed Team access; no old invitations are reactivated."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0078"
down_revision = "20261112_0077"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_team_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("owner_customer_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("mobile_number", sa.String(20), nullable=False),
        sa.Column("scope_type", sa.String(10), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("preset", sa.String(20), nullable=False),
        sa.Column("permissions", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_customer_id", "user_id", "scope_type", "scope_id", name="uq_customer_team_scope"
        ),
    )
    for column in ("merchant_id", "owner_customer_id", "user_id", "scope_id", "status"):
        op.create_index("ix_customer_team_members_" + column, "customer_team_members", [column])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM customer_team_members")):
        raise RuntimeError("Cannot discard customer team audit history")
    op.drop_table("customer_team_members")
