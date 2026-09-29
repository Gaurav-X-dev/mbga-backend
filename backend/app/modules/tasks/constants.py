"""Task vocabulary: statuses, priorities, and the words the activity log is written in.

A **task** is one merchant's staff telling each other to do something, and chasing it. It is
deliberately the loosest-governed module in the platform: spec "Scope" says one flat permission
gates the whole thing, and any staff member holding it may create a task, assign it to anyone,
update anyone's task and post on it. That is not an oversight to tighten - the frontend is built
that way and does not expect a 403 on somebody else's task, so adding a rule here would break
screens silently rather than protect anything.

What *is* enforced is tenancy: a task belongs to a merchant, and another merchant's task does not
exist as far as this module is concerned.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING = "PENDING"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskCategory(StrEnum):
    GENERAL = "GENERAL"
    STOCK = "STOCK"
    DELIVERY = "DELIVERY"
    CUSTOMER = "CUSTOMER"
    MAINTENANCE = "MAINTENANCE"
    ADMIN = "ADMIN"


class TaskRelatedType(StrEnum):
    """What a task points at elsewhere in the platform."""

    CUSTOMER = "CUSTOMER"
    ORDER = "ORDER"
    DELIVERY = "DELIVERY"
    INVENTORY = "INVENTORY"


class TaskMessageKind(StrEnum):
    """`STATUS_CHANGE` rows are written by the server, never posted by a client."""

    COMMENT = "COMMENT"
    STATUS_CHANGE = "STATUS_CHANGE"
    SYSTEM = "SYSTEM"


class AttachmentKind(StrEnum):
    IMAGE = "IMAGE"
    FILE = "FILE"


class TaskScope(StrEnum):
    """The list screen's four tabs (spec #2 `scope`)."""

    ALL = "ALL"
    #: Tasks the caller is an assignee on.
    MY = "MY"
    #: Tasks the caller created - the screen calls this "Assigned by Me".
    ASSIGNED = "ASSIGNED"
    #: Completed, regardless of who created or was assigned.
    COMPLETED = "COMPLETED"


class DueFilter(StrEnum):
    TODAY = "TODAY"
    TOMORROW = "TOMORROW"
    THIS_WEEK = "THIS_WEEK"
    #: Past due and not finished. A completed task is never overdue, however late it was.
    OVERDUE = "OVERDUE"


#: Human labels for a status, used in the activity log and the status-change message. The app
#: renders those strings verbatim, so these are what a staff member actually reads.
STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.NOT_STARTED: "Not Started",
    TaskStatus.IN_PROGRESS: "In Progress",
    TaskStatus.PENDING: "Pending",
    TaskStatus.ON_HOLD: "On Hold",
    TaskStatus.COMPLETED: "Completed",
}

#: Completing a task forces progress to 100 whatever the request said (spec #7, step 2). A task
#: that is done but sitting at 40% is a number nobody believes.
COMPLETION_PROGRESS = 100

MIN_PROGRESS = 0
MAX_PROGRESS = 100

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5_000
MAX_MESSAGE_LENGTH = 5_000
#: How many people one task may be assigned to. Not in the spec; a bound exists because the
#: assignee list is written into an activity line and a notification, and an unbounded list is a
#: request body that can be made arbitrarily expensive.
MAX_ASSIGNEES = 25
MAX_ATTACHMENTS_PER_WRITE = 10

#: Spec #2: page defaults. The list is the screen's home tab, so the page is small and the app
#: pages as the user scrolls.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: Sort is fixed (spec #2: "`updatedAt` descending, always"). Kept here so the one place that
#: orders the list does not invite a query parameter later without a decision.
SORT_DESCRIPTION = "updatedAt descending"

# --- What the activity log says -----------------------------------------------------------------
#
# Rendered verbatim as "{actorName} {action}" (spec #5), so these are lowercase, present tense and
# carry no trailing punctuation. They are templates rather than free text at the call site because
# the timeline reads as one voice, and a second phrasing for the same event is immediately obvious
# to anyone scrolling it.

ACTION_CREATED = "created this task"
ACTION_POSTED = "posted an update"


def action_assigned(names: list[str]) -> str:
    return f"assigned this task to {', '.join(names)}"


def action_mentioned(names: list[str]) -> str:
    return f"mentioned {', '.join(names)}"


def action_uploaded(name: str) -> str:
    return f"uploaded {name}"


def action_status(status: TaskStatus) -> str:
    """"marked this task Completed" reads better than "changed status to Completed"."""
    if status is TaskStatus.COMPLETED:
        return f"marked this task {STATUS_LABELS[status]}"
    return f"changed status to {STATUS_LABELS[status]}"


def action_progress(progress: int) -> str:
    return f"updated progress to {progress}%"


def message_status(status: TaskStatus, note: str | None = None) -> str:
    """The `STATUS_CHANGE` message body. A note sent alongside is appended, not lost."""
    text = f"changed status to {STATUS_LABELS[status]}"
    return f"{text} — {note}" if note else text


def message_progress(progress: int) -> str:
    return f"updated progress to {progress}%"
