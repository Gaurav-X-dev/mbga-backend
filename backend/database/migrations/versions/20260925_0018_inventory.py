"""Warehouse inventory: live cylinder counts per merchant, and the movement ledger behind them.

Two new tables, nothing altered, so this is additive and safe to apply to a running deployment.
No merchant needs seeding: `stock_items` rows are created on the first movement for a cylinder
type, and the snapshot endpoint renders a missing row as zeros. That is what lets this ship
without a data backfill for every existing merchant.

Written to apply on both MariaDB 10.4 (local) and MySQL 8.4 (compose), so there are no
generated columns and no CHECK constraints here - the "no bucket may go negative" rule is
enforced in `app/modules/inventory/ledger.py`, where a violation can be returned as the coded
409 the app reads instead of a driver error.

Revision ID: 20260925_0018
Revises: 20260924_0017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260925_0018"
down_revision = "20260924_0017"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)
#: DATETIME(6) for the ledger: whole seconds lose the order of the several movements one
#: dispatch writes, and the history screen reads them back shuffled. See `inventory/models.py`.
LEDGER_TIME = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    _create_stock_items()
    _create_stock_movements()


def downgrade() -> None:
    # Tables only. Dropping an index that backs a foreign key fails on MySQL, and the indexes
    # here go with their tables anyway.
    op.drop_table("stock_movements")
    op.drop_table("stock_items")


def _create_stock_items() -> None:
    op.create_table(
        "stock_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        # Server defaults so a row inserted by anything other than the ORM still starts at zero
        # rather than at NULL, which would make every later count NULL too.
        sa.Column("filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("empty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damaged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        # One row per cylinder type per merchant. This is also the row every movement locks,
        # so two staff recording stock for the same cylinder serialise on it.
        sa.UniqueConstraint("merchant_id", "cylinder_type", name="uq_stock_items_merchant_type"),
    )
    op.create_index("ix_stock_items_merchant_id", "stock_items", ["merchant_id"])


def _create_stock_movements() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("cylinder_type", sa.String(40), nullable=False),
        # Always positive: the size of the movement. Direction lives in the deltas.
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("delta_filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delta_empty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delta_damaged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bucket", sa.String(10), nullable=True),
        # A correction's before and after. Null on every other type; without them a correction
        # reads as "filled -3" with no way to tell whether the count was 240 or 24.
        sa.Column("previous_count", sa.Integer(), nullable=True),
        sa.Column("new_count", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("reference_type", sa.String(20), nullable=True),
        sa.Column("reference_id", sa.String(120), nullable=True),
        # Nullable, and no foreign key to users: the ledger has to keep reading correctly after
        # the person who recorded a movement has left and their account is gone.
        sa.Column("recorded_by_user_id", sa.String(36), nullable=True),
        sa.Column("recorded_by_name", sa.String(160), nullable=True),
        sa.Column("recorded_at", LEDGER_TIME, nullable=False),
    )
    op.create_index("ix_stock_movements_merchant_id", "stock_movements", ["merchant_id"])
    # The history screen, with and without the cylinder filter.
    op.create_index(
        "ix_stock_movements_merchant_recorded", "stock_movements", ["merchant_id", "recorded_at"]
    )
    op.create_index(
        "ix_stock_movements_merchant_type_recorded",
        "stock_movements",
        ["merchant_id", "cylinder_type", "recorded_at"],
    )
    # Reconciling a delivery slip or a BPCL challan back to the counts it moved.
    op.create_index(
        "ix_stock_movements_reference", "stock_movements", ["reference_type", "reference_id"]
    )
