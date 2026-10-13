"""Customer credit limits, audit trail and runtime reminder controls.

Revision ID: 20261010_0040
Revises: 20261009_0039
"""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0040"
down_revision = "20261009_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_profiles",
        sa.Column("credit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "customer_profiles",
        sa.Column("credit_limit", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("customer_profiles", sa.Column("credit_days", sa.Integer(), nullable=True))
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_reminder_interval_hours", sa.Integer(), nullable=False, server_default="24"
        ),
    )
    op.add_column(
        "platform_settings",
        sa.Column("credit_reminder_max_count", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "platform_settings",
        sa.Column("credit_quiet_start_hour", sa.Integer(), nullable=False, server_default="21"),
    )
    op.add_column(
        "platform_settings",
        sa.Column("credit_quiet_end_hour", sa.Integer(), nullable=False, server_default="8"),
    )
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_reminder_threshold_percent", sa.Integer(), nullable=False, server_default="100"
        ),
    )
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_block_push_cooldown_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
    )
    op.add_column(
        "platform_settings",
        sa.Column(
            "credit_reminder_template",
            sa.Text(),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE platform_settings SET credit_reminder_template = "
            "'Hello {customer_name}, outstanding is INR {outstanding}. "
            "Limit: INR {limit}; available: INR {available}.' "
            "WHERE credit_reminder_template IS NULL"
        )
    )
    op.alter_column(
        "platform_settings",
        "credit_reminder_template",
        existing_type=sa.Text(),
        nullable=False,
    )

    op.create_table(
        "credit_settings_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("merchant_id", sa.String(36), nullable=True),
        sa.Column("old_enabled", sa.Boolean(), nullable=False),
        sa.Column("new_enabled", sa.Boolean(), nullable=False),
        sa.Column("old_limit", sa.BigInteger(), nullable=False),
        sa.Column("new_limit", sa.BigInteger(), nullable=False),
        sa.Column("old_days", sa.Integer(), nullable=True),
        sa.Column("new_days", sa.Integer(), nullable=True),
        sa.Column("changed_by_user_id", sa.String(36), nullable=False),
        sa.Column("changed_by_name", sa.String(160), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_credit_audit_customer_created", "credit_settings_audit", ["customer_id", "created_at"]
    )
    op.create_index(
        "ix_credit_settings_audit_merchant_id", "credit_settings_audit", ["merchant_id"]
    )
    op.create_table(
        "credit_override_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("order_id", sa.String(36), nullable=True),
        sa.Column("merchant_id", sa.String(36), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("used_credit", sa.BigInteger(), nullable=False),
        sa.Column("credit_limit", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), nullable=False),
        sa.Column("approved_by_name", sa.String(160), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_credit_override_customer_created",
        "credit_override_audit",
        ["customer_id", "created_at"],
    )
    op.create_index("ix_credit_override_audit_order_id", "credit_override_audit", ["order_id"])
    op.create_index(
        "ix_credit_override_audit_merchant_id", "credit_override_audit", ["merchant_id"]
    )
    op.create_table(
        "credit_reminder_states",
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), primary_key=True
        ),
        sa.Column("cycle_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("credit_reminder_states")
    op.drop_table("credit_override_audit")
    op.drop_table("credit_settings_audit")
    for column in (
        "credit_reminder_template",
        "credit_block_push_cooldown_minutes",
        "credit_reminder_threshold_percent",
        "credit_quiet_end_hour",
        "credit_quiet_start_hour",
        "credit_reminder_max_count",
        "credit_reminder_interval_hours",
        "credit_reminders_enabled",
        "credit_limit_enabled",
    ):
        op.drop_column("platform_settings", column)
    for column in ("credit_days", "credit_limit", "credit_enabled"):
        op.drop_column("customer_profiles", column)
