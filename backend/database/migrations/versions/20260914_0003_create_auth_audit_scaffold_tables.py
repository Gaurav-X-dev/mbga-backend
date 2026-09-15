"""create auth and audit scaffold tables

Revision ID: 20260914_0003
Revises: 20260914_0002
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None

MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)

    op.create_table(
        "login_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=255), nullable=False),
        sa.Column("device_id", sa.String(length=100), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_login_sessions_user_id", table_name="login_sessions")
    op.drop_table("login_sessions")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_table("audit_logs")
