"""session device details and OTP delivery tracking

Revision ID: 20260917_0010
Revises: 20260917_0009
Create Date: 2026-09-17

- login_sessions: device type, name, app version and push token of the device holding the session.
  The push token is cleared when the session is revoked.
- otp_challenges: delivery status, provider and provider reference.
All columns are nullable; existing rows are unchanged. Rollback: downgrade drops the columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "20260917_0010"
down_revision = "20260917_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("login_sessions", sa.Column("device_type", sa.String(length=20), nullable=True))
    op.add_column("login_sessions", sa.Column("device_name", sa.String(length=100), nullable=True))
    op.add_column("login_sessions", sa.Column("app_version", sa.String(length=40), nullable=True))
    op.add_column("login_sessions", sa.Column("push_token", sa.String(length=512), nullable=True))

    op.add_column("otp_challenges", sa.Column("delivery_status", sa.String(length=20), nullable=True))
    op.add_column("otp_challenges", sa.Column("delivery_provider", sa.String(length=20), nullable=True))
    op.add_column("otp_challenges", sa.Column("delivery_reference", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("otp_challenges", "delivery_reference")
    op.drop_column("otp_challenges", "delivery_provider")
    op.drop_column("otp_challenges", "delivery_status")

    op.drop_column("login_sessions", "push_token")
    op.drop_column("login_sessions", "app_version")
    op.drop_column("login_sessions", "device_name")
    op.drop_column("login_sessions", "device_type")
