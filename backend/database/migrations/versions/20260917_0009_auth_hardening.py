"""refresh-token families, request throttling and authentication audit fields

Revision ID: 20260917_0009
Revises: 20260917_0008
Create Date: 2026-09-17

- login_sessions.family_id / rotated_at: refresh-token reuse detection. Existing sessions keep NULL and are
  treated as their own family.
- otp_challenges.dispatch_suppressed: codes recorded for unknown or ineligible accounts (never sent).
- auth_throttle_events: per-IP / per-device / per-number request counters shared by all app instances.
- audit_logs: channel, result, masked mobile, hashed device and client IP for authentication events.
Rollback: downgrade drops the new table, columns and indexes; no existing rows are changed.
"""
import sqlalchemy as sa
from alembic import op

revision = "20260917_0009"
down_revision = "20260917_0008"
branch_labels = None
depends_on = None

MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.add_column("login_sessions", sa.Column("family_id", sa.String(length=36), nullable=True))
    op.add_column("login_sessions", sa.Column("rotated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_login_sessions_family_id", "login_sessions", ["family_id"], unique=False)

    op.add_column(
        "otp_challenges",
        sa.Column("dispatch_suppressed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_otp_challenges_ip_created", "otp_challenges", ["ip_address", "created_at"], unique=False)
    op.create_index("ix_otp_challenges_mobile_created", "otp_challenges", ["mobile_number", "created_at"], unique=False)

    op.create_table(
        "auth_throttle_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bucket", sa.String(length=40), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_auth_throttle_bucket_key_created", "auth_throttle_events", ["bucket", "key_hash", "created_at"], unique=False)
    op.create_index("ix_auth_throttle_created", "auth_throttle_events", ["created_at"], unique=False)

    op.add_column("audit_logs", sa.Column("login_channel", sa.String(length=30), nullable=True))
    op.add_column("audit_logs", sa.Column("result", sa.String(length=20), nullable=True))
    op.add_column("audit_logs", sa.Column("reason_code", sa.String(length=60), nullable=True))
    op.add_column("audit_logs", sa.Column("masked_mobile", sa.String(length=20), nullable=True))
    op.add_column("audit_logs", sa.Column("device_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=45), nullable=True))
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    for column in ("ip_address", "device_hash", "masked_mobile", "reason_code", "result", "login_channel"):
        op.drop_column("audit_logs", column)

    op.drop_index("ix_auth_throttle_created", table_name="auth_throttle_events")
    op.drop_index("ix_auth_throttle_bucket_key_created", table_name="auth_throttle_events")
    op.drop_table("auth_throttle_events")

    op.drop_index("ix_otp_challenges_mobile_created", table_name="otp_challenges")
    op.drop_index("ix_otp_challenges_ip_created", table_name="otp_challenges")
    op.drop_column("otp_challenges", "dispatch_suppressed")

    op.drop_index("ix_login_sessions_family_id", table_name="login_sessions")
    op.drop_column("login_sessions", "rotated_at")
    op.drop_column("login_sessions", "family_id")
