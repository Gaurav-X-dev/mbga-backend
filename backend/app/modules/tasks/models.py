"""Task tables: the task, who it is on, the thread, its attachments and its history.

The spec's data model is followed closely, with one substitution stated up front: it writes
`branch_id NOT NULL -- same tenancy scoping as every other merchant table`, and in this codebase
that column is **`merchant_id`**. There are no branch rows; a merchant is the tenant, and the
`branchName` the app shows comes off the merchant. Inventing a `branch_id` that always held a
merchant id would leave two names for one thing in a schema people have to read for years.

Five tables:

* `tasks` - the task itself, with its denormalised `created_by_name` and `message_count`.
* `task_assignees` - who it is on. A join table because a task is genuinely many-to-many.
* `task_messages` - the thread, both people's comments and the server's status entries.
* `task_message_mentions` - who a message pinged.
* `task_attachments` - files, which hang off the **task** and optionally off a message.
* `task_activity_log` - the audit strip, append-only.

`task_attachments.task_id` is what makes an attachment appear both in the chat bubble and in the
task's aggregate list, with no second row: the spec calls this out explicitly, because the mock's
in-memory version kept two copies and they could drift.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

#: Microsecond precision wherever order carries meaning here: the thread, the activity strip, and
#: `tasks.updated_at`, which is the list's sole sort key. Plain MySQL DATETIME keeps whole seconds,
#: so two tasks touched in the same second tie and the list claims the wrong one changed last -
#: which on a busy team is most of the time. The same reasoning as `inventory/models.py`'s ledger.
NARRATIVE_TIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # No unique constraint on (merchant_id, task_number): the counter is platform-wide and
        # `id` is the primary key, so uniqueness is already guaranteed by the id itself.
        # The list screen: this merchant, newest activity first. Every scope and filter narrows
        # this same index.
        Index("ix_tasks_merchant_updated", "merchant_id", "updated_at"),
        # The "Assigned by Me" tab, and the due-date filters.
        Index("ix_tasks_merchant_creator", "merchant_id", "created_by_user_id"),
        Index("ix_tasks_merchant_status_due", "merchant_id", "status", "due_date"),
    )

    # `TASK-000123`. The spec's id *is* the readable string - unlike orders and slips, which carry
    # a UUID plus a number - because the frontend's `Task.id` is what the app deep-links on and
    # what the activity rows quote. Keeping one value avoids a second id the app would ignore.
    #
    # That also forces the counter behind it to be platform-wide rather than per merchant; see
    # `numbering.py`.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    # The numeric part, kept so the list has a cheap integer tie-break for same-instant updates.
    task_number: Mapped[int] = mapped_column(Integer)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), index=True)
    priority: Mapped[str] = mapped_column(String(10))
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # What the task is about elsewhere in the platform. Not a foreign key: it points across four
    # different domains, and a task must survive the thing it refers to being archived.
    related_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    related_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Resolved once at creation and stored, so the list renders without four conditional joins
    # and still reads correctly after the customer is renamed.
    related_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_by_user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Denormalised the same way `Order.customer_name` is, and for the same reason: the list would
    # otherwise join users for every row to print one string.
    created_by_name: Mapped[str] = mapped_column(String(160))

    due_date: Mapped[date] = mapped_column(Date)
    # "HH:mm", or null for "no specific time". A string rather than a TIME column because that is
    # what the app sends and shows, and a null-able TIME buys nothing here.
    due_time: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Kept on the row rather than counted: the list shows it on every card, and counting the
    # thread per card is the classic N+1 on the busiest screen in the module.
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Bumped by every write, and the sole sort key for the list - so it needs sub-second
    # precision, or "what changed last" is untrue within any given second.
    updated_at: Mapped[datetime] = mapped_column(NARRATIVE_TIME, index=True)


class TaskAssignee(Base):
    """Who the task is on. Composite key, so assigning the same person twice is impossible."""

    __tablename__ = "task_assignees"
    __table_args__ = (Index("ix_task_assignees_user", "user_id"),)

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskMessage(Base):
    """One entry in the thread: a person's comment, or the server's record of a change."""

    __tablename__ = "task_messages"
    __table_args__ = (
        # The chat feed: one task, oldest first.
        Index("ix_task_messages_task_created", "task_id", "created_at"),
    )

    # `MSG-000789`, for the same reason the task id is readable.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    author_user_id: Mapped[str] = mapped_column(String(36))
    # Denormalised, so a thread renders without joining users per bubble.
    author_name: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Set only on `STATUS_CHANGE` rows. Stored rather than parsed back out of `text`, so the
    # timeline stays machine-readable if the wording is ever changed.
    status_change_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status_change_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    progress_change_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_change_to: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(NARRATIVE_TIME)


class TaskMessageMention(Base):
    """Who a message pinged. The name is re-resolved on read, never trusted from the client."""

    __tablename__ = "task_message_mentions"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("task_messages.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class TaskAttachment(Base):
    """A file on a task, and optionally on one message in it.

    `task_id` is always set; `message_id` is null when the file came in with the task itself,
    before any message existed. One row serves both views - the chat bubble reads it by
    `message_id`, the task's file tab reads every row by `task_id` - which is what stops the two
    lists drifting apart.
    """

    __tablename__ = "task_attachments"
    __table_args__ = (
        Index("ix_task_attachments_task_uploaded", "task_id", "uploaded_at"),
        Index("ix_task_attachments_message", "message_id"),
    )

    # `ATT-000456`.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_messages.id", ondelete="CASCADE"), nullable=True
    )
    # The `fileId` from `POST /documents`. The bytes live in the existing document store; this is
    # the association, so a task attachment is never a second copy of a file.
    document_file_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    # Name, type and size are resolved from the documents table at attach time and copied here -
    # never taken from the request, which the spec is explicit about.
    name: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by_user_id: Mapped[str] = mapped_column(String(36))
    uploaded_by_name: Mapped[str] = mapped_column(String(160))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskActivity(Base):
    """The audit strip. Append-only, and rendered verbatim as "{actorName} {action}"."""

    __tablename__ = "task_activity_log"
    __table_args__ = (Index("ix_task_activity_task_created", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str] = mapped_column(String(36))
    actor_name: Mapped[str] = mapped_column(String(160))
    # Lowercase, present tense, no trailing punctuation - see `constants.py`.
    action: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(NARRATIVE_TIME)


class TaskNumberSequence(Base):
    """Concurrency-safe counter behind `TASK-000123`, one row per merchant.

    Same shape and locking as `OrderNumberSequence` and `DeliveryNumberSequence`.
    """

    __tablename__ = "task_number_sequences"

    prefix: Mapped[str] = mapped_column(String(80), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
