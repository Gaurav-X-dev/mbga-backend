"""Versioned admin-managed public privacy policy."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

CONTENT = sa.Text().with_variant(MEDIUMTEXT(), "mysql", "mariadb")
revision = "20261028_0064"
down_revision = "20261028_0063"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legal_documents",
        sa.Column("slug", sa.String(60), primary_key=True),
        sa.Column("draft_json", CONTENT, nullable=False),
        sa.Column("published_json", CONTENT, nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(160), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "legal_document_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("content_json", CONTENT, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("actor_name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", "revision", name="uq_legal_revision"),
    )
    op.create_index("ix_legal_document_revisions_slug", "legal_document_revisions", ["slug"])


def downgrade():
    op.drop_index("ix_legal_document_revisions_slug", table_name="legal_document_revisions")
    op.drop_table("legal_document_revisions")
    op.drop_table("legal_documents")
