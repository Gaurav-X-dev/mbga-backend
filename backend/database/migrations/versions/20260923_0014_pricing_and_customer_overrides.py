"""Standard-tier pricing months, mid-month change logs and per-customer price overrides.

Additive throughout: five new tables, no existing table or column is touched, so every row
written before this migration stays valid and the deploy needs no backfill.

`pricing_entries.customer_price` is a **stored generated column** (MySQL 8), which is what
keeps `bpcl_base_rate + tier_markup` out of reach of anything that writes the row.

Revision ID: 20260923_0014
Revises: 20260923_0013
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0014"
down_revision = "20260923_0013"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)
MONEY = sa.Numeric(10, 2)


def upgrade() -> None:
    _create_pricing_months()
    _create_pricing_entries()
    _create_pricing_change_logs()
    _create_customer_price_overrides()
    _create_customer_price_override_logs()


def downgrade() -> None:
    """Children before parents, tables only.

    The indexes are deliberately not dropped first: MySQL backs a foreign key with the
    leftmost index that covers its column, so dropping
    `ix_pricing_change_logs_month_type` while `pricing_change_logs` still exists is
    refused with "needed in a foreign key constraint". Dropping the table takes its
    indexes with it.
    """
    op.drop_table("customer_price_override_logs")
    op.drop_table("customer_price_overrides")
    op.drop_table("pricing_change_logs")
    op.drop_table("pricing_entries")
    op.drop_table("pricing_months")


def _create_pricing_months() -> None:
    op.create_table(
        "pricing_months",
        sa.Column("id", sa.String(120), primary_key=True),
        # Each merchant prices independently, so a month belongs to one of them.
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
        # ACTIVE | DRAFT | ARCHIVED. Kept as a string, like every other status column here,
        # rather than a CHECK the application would then duplicate.
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("gst_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("updated_by", sa.String(160), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        # One month per merchant, which is what makes "the current month" unambiguous.
        sa.UniqueConstraint("merchant_id", "month", name="uq_pricing_months_merchant_month"),
    )
    op.create_index("ix_pricing_months_merchant_status", "pricing_months", ["merchant_id", "status"])


def _create_pricing_entries() -> None:
    op.create_table(
        "pricing_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "pricing_month_id",
            sa.String(120),
            sa.ForeignKey("pricing_months.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        # STANDARD | PREFERRED | KEY_ACCOUNT | BULK. Only STANDARD is populated today; the
        # column is here so the other tiers need no migration when they are switched on.
        sa.Column("tier", sa.String(20), nullable=False, server_default="STANDARD"),
        sa.Column("bpcl_base_rate", MONEY, nullable=False),
        sa.Column("tier_markup", MONEY, nullable=False),
        # Computed by the database: a client-sent total can never land here.
        #
        # Declared nullable although it never is: MariaDB rejects `NOT NULL` after a STORED
        # generated column, and the value cannot be null anyway because both of its inputs
        # are NOT NULL. Leaving it off is what keeps this one migration running on both
        # MariaDB (local) and MySQL 8 (compose/deploy).
        sa.Column(
            "customer_price",
            MONEY,
            sa.Computed("bpcl_base_rate + tier_markup", persisted=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "pricing_month_id", "cylinder_type", "tier", name="uq_pricing_entries_month_type_tier"
        ),
    )


def _create_pricing_change_logs() -> None:
    op.create_table(
        "pricing_change_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Denormalised from the month so the log lists for a merchant without a join, and
        # so the tenancy filter cannot be forgotten on the list endpoint.
        sa.Column("merchant_id", sa.String(36), nullable=False, index=True),
        sa.Column("pricing_month_id", sa.String(120), sa.ForeignKey("pricing_months.id"), nullable=False),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        # Null when this is the first rate the entry ever carried.
        sa.Column("old_bpcl_base_rate", MONEY, nullable=True),
        sa.Column("old_tier_markup", MONEY, nullable=True),
        sa.Column("old_customer_price", MONEY, nullable=True),
        sa.Column("new_bpcl_base_rate", MONEY, nullable=False),
        sa.Column("new_tier_markup", MONEY, nullable=False),
        sa.Column("new_customer_price", MONEY, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        # The acting user, copied from the session - never from a request body.
        sa.Column("changed_by_user_id", sa.String(36), nullable=False),
        sa.Column("changed_by_name", sa.String(160), nullable=False),
        sa.Column("changed_by_role", sa.String(60), nullable=False),
        sa.Column("changed_at", TIMESTAMP, nullable=False),
    )
    op.create_index(
        "ix_pricing_change_logs_merchant_effective",
        "pricing_change_logs",
        ["merchant_id", "effective_from"],
    )
    op.create_index(
        "ix_pricing_change_logs_month_type",
        "pricing_change_logs",
        ["pricing_month_id", "cylinder_type", "tier"],
    )


def _create_customer_price_overrides() -> None:
    op.create_table(
        "customer_price_overrides",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # The customer table in this schema is `customer_profiles`; it is already scoped to
        # a merchant, so the override inherits that tenancy rather than repeating it.
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customer_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        # The final per-cylinder, GST-inclusive price for this customer.
        sa.Column("override_price", MONEY, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("set_by_user_id", sa.String(36), nullable=False),
        sa.Column("set_by_name", sa.String(160), nullable=False),
        sa.Column("set_at", TIMESTAMP, nullable=False),
        # At most one override per customer and cylinder type, so "the override" that
        # quoting and billing read is a single, unambiguous row.
        sa.UniqueConstraint(
            "customer_id", "cylinder_type", name="uq_customer_price_overrides_customer_type"
        ),
    )


def _create_customer_price_override_logs() -> None:
    op.create_table(
        "customer_price_override_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customer_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        # SET | UPDATE | REMOVE.
        sa.Column("action", sa.String(10), nullable=False),
        # Null on the first SET; new_override_price is null on REMOVE.
        sa.Column("old_override_price", MONEY, nullable=True),
        sa.Column("new_override_price", MONEY, nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by_user_id", sa.String(36), nullable=False),
        sa.Column("changed_by_name", sa.String(160), nullable=False),
        sa.Column("changed_by_role", sa.String(60), nullable=False),
        sa.Column("changed_at", TIMESTAMP, nullable=False),
    )
    op.create_index(
        "ix_customer_price_override_logs_customer_type",
        "customer_price_override_logs",
        ["customer_id", "cylinder_type"],
    )
