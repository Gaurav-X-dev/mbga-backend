"""Task management: tasks, assignees, the thread, mentions, attachments and the activity log.

Six new tables and nothing altered, so this is additive and safe on a running deployment. No
backfill: tasks start when staff start raising them.

One substitution from the spec's DDL, stated where a reader will find it: it writes
`branch_id NOT NULL -- same tenancy scoping as every other merchant table`, and in this codebase
that column is **`merchant_id`**. There are no branch rows; a merchant is the tenant, and the
`branchName` the app shows comes off the merchant record. A `branch_id` that always held a
merchant id would be two names for one thing in a schema people read for years.

The spec's `CHECK` constraints on the enums are not carried over. MariaDB 10.4 and MySQL 8.4
differ in how they enforce them, and the values are already validated in
`app/modules/tasks/validation.py`, where a bad one comes back as the coded 422 the app reads
instead of a driver error it cannot.

Revision ID: 20260925_0020
Revises: 20260925_0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260925_0020"
down_revision = "20260925_0019"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)
#: DATETIME(6) wherever order carries meaning: the thread, the activity strip, and
#: `tasks.updated_at`, which is the list's only sort key. Whole seconds tie, and the list then
#: claims the wrong task changed last.
NARRATIVE_TIME = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    _create_tasks()
    _create_assignees()
    _create_messages()
    _create_mentions()
    _create_attachments()
    _create_activity()
    _create_sequence()


def downgrade() -> None:
    # Children first. Dropping an index that backs a foreign key fails on MySQL, and these
    # indexes go with their tables anyway.
    op.drop_table("task_activity_log")
    op.drop_table("task_attachments")
    op.drop_table("task_message_mentions")
    op.drop_table("task_messages")
    op.drop_table("task_assignees")
    op.drop_table("tasks")
    op.drop_table("task_number_sequences")


def _create_tasks() -> None:
    op.create_table(
        "tasks",
        # `TASK-000123`. The readable string *is* the id, unlike orders and slips which carry a
        # UUID plus a number: the frontend deep-links on `Task.id` and the activity rows quote it,
        # so a second id would only ever be ignored. That is also why the counter behind it is
        # platform-wide rather than per merchant - two merchants both starting at 1 would collide
        # on this primary key.
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("task_number", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(20), nullable=True),
        # Points across four different domains, so not a foreign key: a task has to survive the
        # thing it refers to being archived.
        sa.Column("related_type", sa.String(20), nullable=True),
        sa.Column("related_id", sa.String(64), nullable=True),
        sa.Column("related_label", sa.String(200), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        # Denormalised the way `orders.customer_name` is: the list would otherwise join users for
        # every row to print one string.
        sa.Column("created_by_name", sa.String(160), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("due_time", sa.String(5), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", NARRATIVE_TIME, nullable=False),
        # No unique constraint on (merchant_id, task_number): the counter is platform-wide and
        # `id` is the primary key, so the id itself already guarantees uniqueness.
    )
    op.create_index("ix_tasks_merchant_id", "tasks", ["merchant_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_updated_at", "tasks", ["updated_at"])
    op.create_index("ix_tasks_created_by", "tasks", ["created_by_user_id"])
    # The list screen: this merchant, newest activity first. Every scope and filter narrows this.
    op.create_index("ix_tasks_merchant_updated", "tasks", ["merchant_id", "updated_at"])
    op.create_index("ix_tasks_merchant_creator", "tasks", ["merchant_id", "created_by_user_id"])
    op.create_index("ix_tasks_merchant_status_due", "tasks", ["merchant_id", "status", "due_date"])


def _create_assignees() -> None:
    op.create_table(
        "task_assignees",
        sa.Column(
            "task_id",
            sa.String(20),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("assigned_at", TIMESTAMP, nullable=False),
    )
    # The "My Tasks" tab: every task one person is on.
    op.create_index("ix_task_assignees_user", "task_assignees", ["user_id"])


def _create_messages() -> None:
    op.create_table(
        "task_messages",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("task_id", sa.String(20), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("author_user_id", sa.String(36), nullable=False),
        sa.Column("author_name", sa.String(160), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # Set only on STATUS_CHANGE rows. Stored rather than parsed back out of `text`, so the
        # thread stays machine-readable if the wording is ever changed.
        sa.Column("status_change_from", sa.String(20), nullable=True),
        sa.Column("status_change_to", sa.String(20), nullable=True),
        sa.Column("progress_change_from", sa.Integer(), nullable=True),
        sa.Column("progress_change_to", sa.Integer(), nullable=True),
        sa.Column("created_at", NARRATIVE_TIME, nullable=False),
    )
    op.create_index("ix_task_messages_task_id", "task_messages", ["task_id"])
    op.create_index("ix_task_messages_task_created", "task_messages", ["task_id", "created_at"])


def _create_mentions() -> None:
    op.create_table(
        "task_message_mentions",
        sa.Column(
            "message_id",
            sa.String(20),
            sa.ForeignKey("task_messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(36), primary_key=True),
    )


def _create_attachments() -> None:
    op.create_table(
        "task_attachments",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("task_id", sa.String(20), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        # Null when the file arrived with the task itself, before any message existed. One row
        # serves both the chat bubble and the task's file tab, which is what stops the two lists
        # drifting apart - the spec calls this out explicitly.
        sa.Column(
            "message_id",
            sa.String(20),
            sa.ForeignKey("task_messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # The `fileId` from POST /documents. The bytes stay in the existing document store, so a
        # task attachment is an association rather than a second copy of a file.
        sa.Column("document_file_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        # Resolved from the documents table at attach time, never taken from the request.
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(36), nullable=False),
        sa.Column("uploaded_by_name", sa.String(160), nullable=False),
        sa.Column("uploaded_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_task_attachments_task_id", "task_attachments", ["task_id"])
    op.create_index("ix_task_attachments_file", "task_attachments", ["document_file_id"])
    op.create_index("ix_task_attachments_task_uploaded", "task_attachments", ["task_id", "uploaded_at"])
    op.create_index("ix_task_attachments_message", "task_attachments", ["message_id"])


def _create_activity() -> None:
    op.create_table(
        "task_activity_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(20), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("actor_name", sa.String(160), nullable=False),
        # Lowercase, present tense, no trailing punctuation - rendered verbatim after the name.
        sa.Column("action", sa.String(500), nullable=False),
        sa.Column("created_at", NARRATIVE_TIME, nullable=False),
    )
    op.create_index("ix_task_activity_task_id", "task_activity_log", ["task_id"])
    op.create_index("ix_task_activity_task_created", "task_activity_log", ["task_id", "created_at"])


def _create_sequence() -> None:
    op.create_table(
        "task_number_sequences",
        sa.Column("prefix", sa.String(80), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
