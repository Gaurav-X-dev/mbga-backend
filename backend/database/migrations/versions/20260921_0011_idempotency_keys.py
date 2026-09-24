"""idempotency keys for retry-sensitive business operations

Revision ID: 20260921_0011
Revises: 20260917_0010
Create Date: 2026-09-21

Phase B infrastructure. Stores one row per (actor, merchant, operation, key) so a mobile
retry of order creation, payment recording or an inventory movement returns the first
result instead of acting twice. Additive: no existing table or column is touched.
Rollback: downgrade drops the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "20260921_0011"
down_revision = "20260917_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        # Empty string, not NULL: MySQL treats NULLs as distinct, which would defeat the
        # unique constraint for customer actors that have no merchant.
        sa.Column("merchant_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PROCESSING"),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("result_reference", sa.String(length=120), nullable=True),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_idempotency_scope_key",
        "idempotency_keys",
        ["actor_user_id", "merchant_id", "operation", "idempotency_key"],
    )
    op.create_index("ix_idempotency_keys_actor_user_id", "idempotency_keys", ["actor_user_id"])
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])
    op.create_index("ix_idempotency_keys_status_created", "idempotency_keys", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_status_created", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_actor_user_id", table_name="idempotency_keys")
    op.drop_constraint("uq_idempotency_scope_key", "idempotency_keys", type_="unique")
    op.drop_table("idempotency_keys")
