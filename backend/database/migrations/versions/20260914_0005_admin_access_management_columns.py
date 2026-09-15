"""admin access management columns

Revision ID: 20260914_0005
Revises: 20260914_0004
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0005"
down_revision = "20260914_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("username", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("full_name", sa.String(length=160), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.add_column("login_sessions", sa.Column("user_agent", sa.String(length=255), nullable=True))
    op.add_column("login_sessions", sa.Column("ip_address", sa.String(length=45), nullable=True))
    op.add_column("login_sessions", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("login_sessions", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("login_sessions", sa.Column("last_activity_at", sa.DateTime(), nullable=True))

    op.add_column("audit_logs", sa.Column("entity_type", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("entity_id", sa.String(length=36), nullable=True))
    op.add_column("audit_logs", sa.Column("message", sa.String(length=255), nullable=True))
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_column("audit_logs", "message")
    op.drop_column("audit_logs", "entity_id")
    op.drop_column("audit_logs", "entity_type")

    op.drop_column("login_sessions", "last_activity_at")
    op.drop_column("login_sessions", "expires_at")
    op.drop_column("login_sessions", "created_at")
    op.drop_column("login_sessions", "ip_address")
    op.drop_column("login_sessions", "user_agent")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "full_name")
    op.drop_column("users", "username")
    op.drop_column("users", "email")
