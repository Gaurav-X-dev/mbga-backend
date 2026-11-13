"""Explicit owner customer for branch hierarchy; existing standalone brands preserved."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0075"
down_revision = "20261111_0074"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer_brands", sa.Column("owner_customer_id", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_customer_brand_owner", "customer_brands", ["owner_customer_id"])
    op.create_foreign_key(
        "fk_customer_brand_owner",
        "customer_brands",
        "customer_profiles",
        ["owner_customer_id"],
        ["id"],
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM customer_brands WHERE owner_customer_id IS NOT NULL")
    ):
        raise RuntimeError("Cannot remove active owner hierarchy")
    op.drop_constraint("fk_customer_brand_owner", "customer_brands", type_="foreignkey")
    op.drop_constraint("uq_customer_brand_owner", "customer_brands", type_="unique")
    op.drop_column("customer_brands", "owner_customer_id")
