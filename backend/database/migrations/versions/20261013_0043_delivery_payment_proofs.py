"""Delivery-bound UPI payment proof metadata.

Revision ID: 20261013_0043
Revises: 20261013_0042
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0043"
down_revision = "20261013_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_slips", sa.Column("payment_proof_url", sa.String(500), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_proof_storage_key", sa.String(255), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_proof_content_type", sa.String(50), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_proof_captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("delivery_slips", sa.Column("payment_proof_uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("proof_url", sa.String(500), nullable=True))
    op.add_column("payments", sa.Column("proof_captured_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "proof_captured_at")
    op.drop_column("payments", "proof_url")
    op.drop_column("delivery_slips", "payment_proof_uploaded_at")
    op.drop_column("delivery_slips", "payment_proof_captured_at")
    op.drop_column("delivery_slips", "payment_proof_content_type")
    op.drop_column("delivery_slips", "payment_proof_storage_key")
    op.drop_column("delivery_slips", "payment_proof_url")
