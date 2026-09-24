"""Response models for the notification screens (spec §3.18, §15)."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.notifications.constants import Category, ReferenceType, Severity

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


class AppNotification(BaseModel):
    """Spec §3.18. One row of the Notifications screen."""

    id: str
    title: str
    # `message` on the wire; the outbox column is `body`.
    message: str
    severity: Severity
    category: Category
    created_at: UtcTime = Field(alias="createdAt")
    # Per-user: a manager marking this read does not hide it from the accountant.
    read: bool
    # Where tapping it goes. Absent when the event has nothing to open.
    reference_type: ReferenceType | None = Field(default=None, alias="referenceType")
    reference_id: str | None = Field(default=None, alias="referenceId")

    model_config = _CAMEL


class UnreadCount(BaseModel):
    """The bell badge. A separate call so the badge does not have to fetch the whole list."""

    unread: int

    model_config = _CAMEL
