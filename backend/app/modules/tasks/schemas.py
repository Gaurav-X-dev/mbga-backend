"""Request and response models for the Tasks screens.

Shapes follow `merchant-app/src/shared/types/task.ts` exactly, because the spec's whole point is
that wiring this up is a drop-in: only the mock bodies in `taskService.ts` change, and no screen
moves. So the field names here are the frontend's, not the database's - `assignedUserIds` is an
array of ids rather than embedded users, `authorId` rather than `authorUserId`, and
`progressChange: {from, to}` rather than two flat columns.

Timestamps go out as UTC with a `Z`, as everywhere else: MySQL DATETIME keeps no offset and a
naive string is read by JS as local time, which on a task due at 18:00 would be a day's confusion.
`dueDate` is a plain ISO date with no time, because that is what the picker sets.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.tasks.constants import (
    MAX_DESCRIPTION_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_TITLE_LENGTH,
    AttachmentKind,
    TaskCategory,
    TaskPriority,
    TaskRelatedType,
    TaskStatus,
)

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- The team picker ------------------------------------------------------------------------------


class TeamMemberResponse(BaseModel):
    """Spec #1. Deliberately the same shape as the `user` object auth already returns, minus
    permissions - the app derives the display title and avatar colour from `role` and `id`
    client-side, so sending them would be two sources for one thing."""

    id: str
    name: str
    role: str
    branch_name: str | None = Field(default=None, alias="branchName")

    model_config = _CAMEL


# --- Attachments ------------------------------------------------------------------------------------


class TaskAttachmentResponse(BaseModel):
    """One file on a task or a message.

    `uri` is set for images and **null for files**, which the spec settles explicitly: an image
    renders inline in the chat grid as soon as the list loads, so it needs a URL up front, while a
    file shows as an icon and is only opened on tap - at which point the app calls
    `GET /documents/{fileId}/url` for a short-lived link, exactly as the KYC screens already do.
    """

    id: str
    kind: AttachmentKind
    uri: str | None = None
    name: str
    mime_type: str = Field(alias="mimeType")
    size: int
    uploaded_by: str = Field(alias="uploadedBy")
    uploaded_by_name: str = Field(alias="uploadedByName")
    uploaded_at: UtcTime = Field(alias="uploadedAt")
    #: The frontend's upload-progress marker. Anything the API returns is already stored.
    status: str = "DONE"
    #: What the app passes to `GET /documents/{fileId}/url` when opening a file attachment.
    file_id: str = Field(alias="fileId")

    model_config = _CAMEL


class AttachmentRequest(BaseModel):
    """What a client sends to attach an already-uploaded file.

    Only `fileId` and `kind` are trusted; name, type and size are resolved server-side from the
    documents table. A client that could set its own `size` would make the file tab lie.
    """

    file_id: str = Field(alias="fileId", max_length=80)
    kind: AttachmentKind

    model_config = _CAMEL


# --- The task ------------------------------------------------------------------------------------


class TaskResponse(BaseModel):
    """Spec #2/#3. One shape for the list and the detail, so the app caches them together."""

    id: str
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    progress: int
    category: TaskCategory | None = None
    #: Ids only. The app resolves names and avatars against the team list from #1.
    assigned_user_ids: list[str] = Field(default_factory=list, alias="assignedUserIds")
    created_by_user_id: str = Field(alias="createdByUserId")
    created_by_name: str = Field(alias="createdByName")
    due_date: date = Field(alias="dueDate")
    due_time: str | None = Field(default=None, alias="dueTime")
    related_type: TaskRelatedType | None = Field(default=None, alias="relatedType")
    related_id: str | None = Field(default=None, alias="relatedId")
    related_label: str | None = Field(default=None, alias="relatedLabel")
    attachments: list[TaskAttachmentResponse] = Field(default_factory=list)
    message_count: int = Field(alias="messageCount")
    created_at: UtcTime = Field(alias="createdAt")
    updated_at: UtcTime = Field(alias="updatedAt")

    model_config = _CAMEL


class TaskPageResponse(BaseModel):
    """Spec #2's envelope. Paged because Tasks is the module's home screen."""

    items: list[TaskResponse]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int

    model_config = _CAMEL


# --- The thread ------------------------------------------------------------------------------------


class MentionResponse(BaseModel):
    user_id: str = Field(alias="userId")
    name: str

    model_config = _CAMEL


class ProgressChange(BaseModel):
    from_: int = Field(alias="from")
    to: int

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class StatusChange(BaseModel):
    from_: TaskStatus = Field(alias="from")
    to: TaskStatus

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class TaskMessageResponse(BaseModel):
    """Spec #4. A comment, or a server-written record of a status or progress change."""

    id: str
    task_id: str = Field(alias="taskId")
    kind: str
    author_id: str = Field(alias="authorId")
    author_name: str = Field(alias="authorName")
    text: str
    mentions: list[MentionResponse] = Field(default_factory=list)
    attachments: list[TaskAttachmentResponse] = Field(default_factory=list)
    status_change: StatusChange | None = Field(default=None, alias="statusChange")
    progress_change: ProgressChange | None = Field(default=None, alias="progressChange")
    created_at: UtcTime = Field(alias="createdAt")

    model_config = _CAMEL


class TaskActivityResponse(BaseModel):
    """Spec #5. Rendered verbatim as "{actorName} {action}"."""

    id: str
    task_id: str = Field(alias="taskId")
    at: UtcTime
    actor_name: str = Field(alias="actorName")
    action: str

    model_config = _CAMEL


# --- Requests ------------------------------------------------------------------------------------


class MentionRequest(BaseModel):
    """Only `userId` is trusted. The name is re-resolved, because the client's copy can be stale
    by the time the message is sent."""

    user_id: str = Field(alias="userId", max_length=36)
    name: str | None = Field(default=None, max_length=160)

    model_config = _CAMEL


class CreateTaskRequest(BaseModel):
    """Spec #6."""

    title: str = Field(max_length=MAX_TITLE_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    assigned_user_ids: list[str] = Field(default_factory=list, alias="assignedUserIds")
    priority: TaskPriority
    due_date: date = Field(alias="dueDate")
    due_time: str | None = Field(default=None, alias="dueTime", max_length=5)
    category: TaskCategory | None = None
    related_type: TaskRelatedType | None = Field(default=None, alias="relatedType")
    related_id: str | None = Field(default=None, alias="relatedId", max_length=64)
    related_label: str | None = Field(default=None, alias="relatedLabel", max_length=200)
    attachments: list[AttachmentRequest] = Field(default_factory=list)

    model_config = _CAMEL


class UpdateTaskStatusRequest(BaseModel):
    """Spec #7. Every field optional, but at least one of the three must be present - which
    `validation.py` enforces, because "all optional" and "not all absent" is not expressible here."""

    status: TaskStatus | None = None
    progress: int | None = None
    note: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)

    model_config = _CAMEL


class PostTaskMessageRequest(BaseModel):
    """Spec #8. Text or attachments - one of the two must carry something."""

    text: str = Field(default="", max_length=MAX_MESSAGE_LENGTH)
    mentions: list[MentionRequest] = Field(default_factory=list)
    attachments: list[AttachmentRequest] = Field(default_factory=list)

    model_config = _CAMEL
