"""Add customer V2 UPI collection intents and FIFO payment linkage.

Revision ID: 20261026_0056
Revises: 20261026_0055
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20261026_0056"
down_revision = "20261026_0055"
branch_labels = None
depends_on = None

_MICROS = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    op.create_table(
        "payment_collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("total_due_at_creation", sa.BigInteger(), nullable=False),
        sa.Column("remaining_balance", sa.BigInteger(), nullable=True),
        sa.Column("credit_used", sa.BigInteger(), nullable=True),
        sa.Column("available_credit", sa.BigInteger(), nullable=True),
        sa.Column("mode", sa.String(10), nullable=False, server_default="UPI"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("upi_uri", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(80), nullable=True),
        sa.Column("allocation_snapshot", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", _MICROS, nullable=True),
        sa.Column("submitted_at", _MICROS, nullable=True),
        sa.Column("created_at", _MICROS, nullable=False),
        sa.Column("updated_at", _MICROS, nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer_profiles.id"]),
        sa.UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_payment_collections_customer_key"
        ),
        sa.UniqueConstraint(
            "merchant_id", "reference", name="uq_payment_collections_merchant_reference"
        ),
    )
    op.create_index("ix_payment_collections_merchant_id", "payment_collections", ["merchant_id"])
    op.create_index("ix_payment_collections_customer_id", "payment_collections", ["customer_id"])
    op.create_index("ix_payment_collections_status", "payment_collections", ["status"])
    op.create_index("ix_payment_collections_expires_at", "payment_collections", ["expires_at"])
    op.create_index(
        "ix_payment_collections_customer_created",
        "payment_collections",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_payment_collections_merchant_status",
        "payment_collections",
        ["merchant_id", "status"],
    )

    op.add_column("payments", sa.Column("collection_id", sa.String(36), nullable=True))
    op.create_index("ix_payments_collection_id", "payments", ["collection_id"])
    op.create_foreign_key(
        "fk_payments_collection_id_payment_collections",
        "payments",
        "payment_collections",
        ["collection_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payments_collection_id_payment_collections", "payments", type_="foreignkey"
    )
    op.drop_index("ix_payments_collection_id", table_name="payments")
    op.drop_column("payments", "collection_id")
    op.drop_table("payment_collections")
