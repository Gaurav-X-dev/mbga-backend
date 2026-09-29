"""Retry bookkeeping on the notification outbox, and per-user read state.

Additive: three nullable/defaulted columns on an existing table and one new table. Rows
written before this migration keep working - `attempts` defaults to 0 and a null
`next_attempt_at` means "due now", which is exactly what an undelivered backlog row is.

Read state is a separate table rather than a column because the same notification is read by
several people: spec §15 says all staff share the merchant bucket, so one row is seen by the
whole team and each of them has their own read flag.

Revision ID: 20260924_0017
Revises: 20260923_0016
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0017"
down_revision = "20260923_0016"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    _extend_outbox()
    _create_notification_reads()


def downgrade() -> None:
    op.drop_table("notification_reads")
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    for column in ("last_error", "next_attempt_at", "attempts"):
        op.drop_column("notification_outbox", column)


def _extend_outbox() -> None:
    # Written only by the dispatcher. A business module queues an event and never touches
    # these, which is what keeps queueing free of any delivery concern.
    op.add_column(
        "notification_outbox",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    # Null means due now for an unsent row, and "given up" for one out of attempts.
    op.add_column("notification_outbox", sa.Column("next_attempt_at", TIMESTAMP, nullable=True))
    # Why the last attempt failed, for an operator reading the table. Never shown to a user.
    op.add_column("notification_outbox", sa.Column("last_error", sa.String(255), nullable=True))
    # The dispatcher's own query: undelivered, not exhausted, back-off elapsed.
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["delivered_at", "next_attempt_at", "attempts"],
    )


def _create_notification_reads() -> None:
    op.create_table(
        "notification_reads",
        # Composite key: one row per user per notification, so marking read twice is a
        # no-op rather than a duplicate.
        sa.Column("notification_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("read_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_notification_reads_user", "notification_reads", ["user_id", "notification_id"])
