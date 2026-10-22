"""Add isolated v2 multi-image KYC mappings.

Revision ID: 20261021_0045
Revises: 20261013_0044

No v1 table is altered and no foreign key is added to a v1 table.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0045"
down_revision = "20261013_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_document_files_v2" in inspector.get_table_names():
        return
    op.create_table(
        "customer_document_files_v2",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("file_id", sa.String(60), nullable=False),
        sa.Column("side", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_customer_document_files_v2_customer_id",
        "customer_document_files_v2",
        ["customer_id"],
    )
    op.create_index(
        "ix_customer_document_files_v2_current",
        "customer_document_files_v2",
        ["customer_id", "document_type", "superseded_at"],
    )
    op.create_index(
        "ix_customer_document_files_v2_file",
        "customer_document_files_v2",
        ["file_id"],
        unique=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_document_files_v2" in inspector.get_table_names():
        op.drop_table("customer_document_files_v2")
