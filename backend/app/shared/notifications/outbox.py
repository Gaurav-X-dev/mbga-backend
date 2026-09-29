"""Queueing business notifications (spec §18.8).

Nothing here sends anything. Events are written to a table inside the *same* transaction as
the business change that caused them, which is what makes the pair atomic: an approval that
rolls back cannot leave an "Account approved" message behind, and a committed approval always
has its message queued. The notification slice will later deliver these rows and stamp
`delivered_at`.

Recipients are identified by id. Titles and bodies never carry a document number, an OTP or
a full mobile number — a notification row is read by support staff and by the apps.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.autodispatch import mark_queued
from app.shared.notifications.models import NotificationOutbox


class Severity:
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    recipient_kind: str
    recipient_id: str
    entity_type: str
    entity_id: str
    title: str
    body: str
    severity: str = Severity.INFO


class NotificationOutboxWriter:
    """The abstraction business services depend on, so the delivery mechanism can change."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def queue(self, event: NotificationEvent) -> None:
        """Add one event to the caller's transaction. The caller still commits.

        Not awaited and not flushed on purpose: a notification must never be the thing that
        decides whether a business write succeeds.

        Marking the request means the middleware kicks off a delivery pass once the response
        has gone out, so a notification does not wait for the worker's next sweep. Nothing
        about that is load-bearing: if the dispatch never happens the row simply stays
        queued, which is what the worker is for.
        """
        mark_queued()
        self.session.add(
            NotificationOutbox(
                id=str(uuid4()),
                event_type=event.event_type,
                recipient_kind=event.recipient_kind,
                recipient_id=event.recipient_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                title=event.title,
                body=event.body,
                severity=event.severity,
                delivered_at=None,
                created_at=datetime.now(UTC),
            )
        )

    async def queue_repeatable(self, event: NotificationEvent) -> None:
        """Queue an event that can legitimately happen to the same entity again.

        The outbox is unique on `(event_type, entity_type, entity_id, recipient_kind,
        recipient_id)`, which is what stops a retried business write from notifying twice. Most
        modules satisfy that by keying `entity_id` on the thing that changed - the stock movement,
        the price change log - so each occurrence is naturally its own row.

        Some events cannot. A task notification has to carry the **task** id, because tapping it
        opens the task; so "Task updated" for the same task is the same key every time, and a
        plain insert would be a duplicate-key error on the second update.

        This refreshes the pending row instead: new wording, new timestamp, and `delivered_at`
        cleared so it is pushed again and sorts back to the top of the bell. A task updated five
        times is then one unread row saying so, which is what a person actually wants - five
        identical rows is how a notification list stops being read.

        Awaited and flushed, unlike `queue()`: an upsert is a statement rather than a pending
        object. It still runs inside the caller's transaction, so a business write that rolls
        back takes the notification with it.
        """
        mark_queued()
        now = datetime.now(UTC)
        statement = mysql_insert(NotificationOutbox).values(
            id=str(uuid4()),
            event_type=event.event_type,
            recipient_kind=event.recipient_kind,
            recipient_id=event.recipient_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            title=event.title,
            body=event.body,
            severity=event.severity,
            delivered_at=None,
            attempts=0,
            created_at=now,
        )
        await self.session.execute(
            statement.on_duplicate_key_update(
                title=statement.inserted.title,
                body=statement.inserted.body,
                severity=statement.inserted.severity,
                created_at=statement.inserted.created_at,
                # Re-opened for delivery: the event happened again, so the device hears again.
                delivered_at=None,
                attempts=0,
                next_attempt_at=None,
                last_error=None,
            )
        )


# --- Where the events live ------------------------------------------------------------------
#
# Deliberately nothing below this line. This module is the **transport**: it defines what an
# event is and writes it to the outbox inside the caller's transaction. The events
# themselves - every title, body, audience and severity the platform can send - are the
# catalogue in `app.modules.notifications.events`, organised by domain.
#
# Keeping them apart is not tidiness. Re-exporting the builders from here made this module
# import the catalogue while the catalogue imported this module for `NotificationEvent`, so
# whichever side was touched first at startup got a half-built module. The package
# `__init__` still re-exports the moved builders, lazily, for callers that used to get them
# from there.
