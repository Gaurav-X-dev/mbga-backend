"""Merchant-scoped customer hierarchy and accepted account memberships."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0074"
down_revision = "20261104_0073"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_brands",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("name", sa.String(160), primary_key=False, nullable=False),
    )
    op.create_index("ix_customer_brands_merchant_id", "customer_brands", ["merchant_id"])
    op.create_table(
        "customer_brand_outlets",
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customer_profiles.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            sa.String(36),
            sa.ForeignKey("customer_brands.id"),
            primary_key=False,
            nullable=False,
        ),
    )
    op.create_index("ix_customer_brand_outlets_brand_id", "customer_brand_outlets", ["brand_id"])
    op.create_table(
        "customer_access_roles",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("name", sa.String(80), primary_key=False, nullable=False),
        sa.Column("permissions", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_customer_access_roles_merchant_id", "customer_access_roles", ["merchant_id"]
    )
    op.create_table(
        "customer_memberships",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(36),
            sa.ForeignKey("merchants.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("scope_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("scope_type", sa.String(10), primary_key=False, nullable=False),
        sa.Column("mobile_number", sa.String(15), primary_key=False, nullable=False),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=False, nullable=True
        ),
        sa.Column(
            "role_id",
            sa.String(36),
            sa.ForeignKey("customer_access_roles.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("status", sa.String(12), primary_key=False, nullable=False),
        sa.Column("created_by", sa.String(36), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("scope_id", "mobile_number", name="uq_customer_membership_phone"),
    )
    op.create_index("ix_customer_memberships_merchant_id", "customer_memberships", ["merchant_id"])
    op.create_index(
        "ix_customer_memberships_mobile_number", "customer_memberships", ["mobile_number"]
    )
    op.create_index("ix_customer_memberships_scope_id", "customer_memberships", ["scope_id"])
    op.create_index("ix_customer_memberships_user_id", "customer_memberships", ["user_id"])


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM customer_memberships")):
        raise RuntimeError("Cannot drop customer access while membership history exists")
    op.drop_table("customer_memberships")
    op.drop_table("customer_brand_outlets")
    op.drop_table("customer_access_roles")
    op.drop_table("customer_brands")
