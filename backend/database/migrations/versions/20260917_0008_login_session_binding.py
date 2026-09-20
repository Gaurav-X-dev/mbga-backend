"""bind login sessions to app channel and token type

Revision ID: 20260917_0008
Revises: 20260916_0007
Create Date: 2026-09-17

Existing sessions keep NULL in the new columns. The session check treats NULL as "legacy" and falls
back to the channel and token type inside the signed token, so no one is signed out by this migration.
Rollback: downgrade drops only the added columns and index; session rows are kept.
"""
import sqlalchemy as sa
from alembic import op

revision = "20260917_0008"
down_revision = "20260916_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("login_sessions", sa.Column("login_channel", sa.String(length=30), nullable=True))
    op.add_column("login_sessions", sa.Column("session_type", sa.String(length=20), nullable=True))
    op.add_column("login_sessions", sa.Column("revoked_reason", sa.String(length=40), nullable=True))
    op.create_index("ix_login_sessions_user_revoked", "login_sessions", ["user_id", "revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_login_sessions_user_revoked", table_name="login_sessions")
    op.drop_column("login_sessions", "revoked_reason")
    op.drop_column("login_sessions", "session_type")
    op.drop_column("login_sessions", "login_channel")
