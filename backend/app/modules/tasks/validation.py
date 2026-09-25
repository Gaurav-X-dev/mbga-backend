"""Field rules for the task endpoints.

Every failure is the coded `VALIDATION_ERROR` envelope with `detail.fields[].field` naming the
input to fix, which is what the frontend's `fieldErrors` map expects.

Two rules here are worth reading twice, because both are the spec being deliberate rather than
loose:

* **A mention that does not resolve is dropped, not rejected.** Somebody can be deactivated
  between the moment a name is typed and the moment send is tapped, and failing the whole message
  for that would lose what the person wrote.
* **A due date may not be in the past.** Not because the data model cares, but because the list's
  `OVERDUE` filter would immediately claim a brand-new task was already late.
"""

from datetime import date

from fastapi import status as http_status

from app.modules.tasks.constants import (
    MAX_ASSIGNEES,
    MAX_ATTACHMENTS_PER_WRITE,
    MAX_PROGRESS,
    MAX_TITLE_LENGTH,
    MIN_PROGRESS,
)
from app.modules.tasks.schemas import (
    CreateTaskRequest,
    PostTaskMessageRequest,
    UpdateTaskStatusRequest,
)
from app.shared.exceptions.api_error import ApiError

EMPTY_MESSAGE = "Write an update or attach a file."


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


# --- Creating ------------------------------------------------------------------------------------


def check_create(payload: CreateTaskRequest, *, today: date) -> str:
    """Validate a new task and return its trimmed title."""
    title = payload.title.strip()
    if not title:
        raise invalid("title", "title_required", "Enter a task title")
    if len(title) > MAX_TITLE_LENGTH:
        raise invalid("title", "title_too_long", f"Keep the title under {MAX_TITLE_LENGTH} characters")

    _check_assignees(payload.assigned_user_ids)
    _check_due(payload.due_date, today)
    _check_due_time(payload.due_time)
    _check_related(payload)
    check_attachments(payload.attachments)
    return title


def _check_assignees(user_ids: list[str]) -> None:
    """At least one, and no duplicates.

    A task on nobody is a note, and the screens have no way to show one: every card renders an
    assignee row, and the "My Tasks" tab is defined by assignment.
    """
    if not user_ids:
        raise invalid("assignedUserIds", "assignees_required", "Assign this task to at least one person")
    if len(user_ids) > MAX_ASSIGNEES:
        raise invalid(
            "assignedUserIds",
            "too_many_assignees",
            f"A task can be assigned to at most {MAX_ASSIGNEES} people",
        )
    if len(set(user_ids)) != len(user_ids):
        # Merged rather than refused would be friendlier, but it hides a client bug that would
        # also double the person's name in the activity line.
        raise invalid("assignedUserIds", "duplicate_assignee", "Someone is listed twice")


def _check_due(due: date, today: date) -> None:
    if due < today:
        raise invalid("dueDate", "due_in_past", "Choose today or a later date")


def _check_due_time(value: str | None) -> None:
    """`HH:mm`, or absent for "no specific time"."""
    if value is None:
        return
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise invalid("dueTime", "due_time_invalid", "Enter a time as HH:mm")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise invalid("dueTime", "due_time_invalid", "Enter a time as HH:mm")


def _check_related(payload: CreateTaskRequest) -> None:
    """`relatedType`, `relatedId` and `relatedLabel` travel together or not at all.

    A type with no id is a chip the app renders and cannot open; an id with no label is a chip
    with nothing written on it.
    """
    present = [
        bool(payload.related_type),
        bool((payload.related_id or "").strip()),
        bool((payload.related_label or "").strip()),
    ]
    if any(present) and not all(present):
        raise invalid(
            "relatedType",
            "related_incomplete",
            "A linked record needs its type, id and label together",
        )


def check_attachments(attachments: list) -> None:
    if len(attachments) > MAX_ATTACHMENTS_PER_WRITE:
        raise invalid(
            "attachments",
            "too_many_attachments",
            f"Attach at most {MAX_ATTACHMENTS_PER_WRITE} files at a time",
        )
    seen = {item.file_id for item in attachments}
    if len(seen) != len(attachments):
        raise invalid("attachments", "duplicate_attachment", "The same file is attached twice")


# --- Updating status ------------------------------------------------------------------------------


def check_update(payload: UpdateTaskStatusRequest) -> str | None:
    """At least one of status, progress or note. Returns the trimmed note."""
    note = (payload.note or "").strip() or None
    if payload.status is None and payload.progress is None and note is None:
        raise invalid("status", "nothing_to_update", "Change the status, the progress or add a note")
    if payload.progress is not None:
        _check_progress(payload.progress)
    return note


def _check_progress(value: int) -> None:
    # `True` is an `int` in Python and would otherwise become 1% progress.
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("progress", "progress_invalid", "Enter a whole number between 0 and 100")
    if not MIN_PROGRESS <= value <= MAX_PROGRESS:
        raise invalid("progress", "progress_out_of_range", "Enter a whole number between 0 and 100")


# --- Posting a message ------------------------------------------------------------------------------


def check_message(payload: PostTaskMessageRequest) -> str:
    """Text or attachments. Returns the trimmed text.

    The spec fixes this message: "Write an update or attach a file." It is shown under the
    composer, so an empty send is explained rather than silently ignored.
    """
    text = (payload.text or "").strip()
    if not text and not payload.attachments:
        raise invalid("text", "message_empty", EMPTY_MESSAGE)
    check_attachments(payload.attachments)
    return text
