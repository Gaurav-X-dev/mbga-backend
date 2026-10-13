"""Scope every notification to exactly one application channel.

Revision ID: 20261008_0036
Revises: 20261008_0035
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0036"
down_revision = "20261008_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_outbox",
        sa.Column("recipient_channel", sa.String(30), nullable=True),
    )
    # All personal/user events shipped before this migration are driver assignment,
    # reassignment or in-transit cancellation events. Customer and merchant rows already
    # name their audience explicitly.
    op.execute(
        sa.text(
            """UPDATE notification_outbox
                  SET recipient_channel = CASE LOWER(recipient_kind)
                    WHEN 'customer' THEN 'CUSTOMER'
                    WHEN 'merchant' THEN 'MERCHANT'
                    WHEN 'user' THEN 'DELIVERY'
                    ELSE 'ADMIN'
                  END
                WHERE recipient_channel IS NULL"""
        )
    )
    op.alter_column(
        "notification_outbox",
        "recipient_channel",
        existing_type=sa.String(30),
        nullable=False,
    )
    op.create_index(
        "ix_notification_outbox_recipient_channel",
        "notification_outbox",
        ["recipient_channel"],
    )
    op.drop_constraint("uq_notification_outbox_event", "notification_outbox", type_="unique")
    op.create_unique_constraint(
        "uq_notification_outbox_event",
        "notification_outbox",
        [
            "event_type",
            "entity_type",
            "entity_id",
            "recipient_kind",
            "recipient_id",
            "recipient_channel",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_notification_outbox_event", "notification_outbox", type_="unique")
    op.create_unique_constraint(
        "uq_notification_outbox_event",
        "notification_outbox",
        ["event_type", "entity_type", "entity_id", "recipient_kind", "recipient_id"],
    )
    op.drop_index("ix_notification_outbox_recipient_channel", table_name="notification_outbox")
    op.drop_column("notification_outbox", "recipient_channel")
