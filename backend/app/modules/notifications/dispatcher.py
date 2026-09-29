"""Draining the notification outbox to FCM.

The business modules queue events on their own transaction and never send anything - an
order that rolls back must not leave "Order placed" behind, and a Firebase outage must never
be the reason an order fails. This is the other half: a worker that picks up what was queued
and delivers it.

What it guarantees, and what it does not:

* **At-least-once, not exactly-once.** A row is stamped delivered only after FCM accepted it.
  A crash between the send and the stamp re-sends on the next pass, which is the right way
  round - a duplicate notification is an annoyance, a missing one is a lost order.
* **A dead token is forgotten, a broken network is retried.** Those are different failures
  and conflating them either spams a retired device forever or drops a real notification.
* **A row with no live device is settled, not retried.** Nobody is signed in to receive it;
  the in-app list still carries it, which is where it will be read.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.constants import category_of, reference_of
from app.modules.notifications.fcm import PushMessage
from app.modules.notifications.projects import FcmProjects
from app.modules.notifications.recipients import RecipientResolver
from app.shared.notifications.models import NotificationOutbox

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 100
#: Given up on after this many failed passes, so one poisoned row cannot hold up the queue
#: forever. It stays in the table, visible, with its last error.
MAX_ATTEMPTS = 5
#: Back-off between attempts, indexed by attempt count.
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))


@dataclass
class DispatchReport:
    """What one pass did. Printed by the worker script and asserted by the tests."""

    considered: int = 0
    delivered: int = 0
    no_devices: int = 0
    retrying: int = 0
    abandoned: int = 0
    tokens_forgotten: int = 0
    #: Devices skipped because their app has no Firebase credential configured.
    unconfigured: int = 0
    #: Devices whose token belongs to a different project than the one it was sent through.
    misrouted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "considered": self.considered,
            "delivered": self.delivered,
            "noDevices": self.no_devices,
            "retrying": self.retrying,
            "abandoned": self.abandoned,
            "tokensForgotten": self.tokens_forgotten,
            "unconfigured": self.unconfigured,
            "misrouted": self.misrouted,
        }


class NotificationDispatcher:
    """One pass over the outbox."""

    def __init__(self, session: AsyncSession, projects: FcmProjects | None) -> None:
        self.session = session
        self.projects = projects
        self.recipients = RecipientResolver(session)

    async def run(self, *, limit: int = DEFAULT_BATCH, now: datetime | None = None) -> DispatchReport:
        """Deliver everything that is due. The caller commits nothing; this commits per row.

        Committing per row rather than per batch is deliberate: a failure on row 40 must not
        re-send the 39 that already went out.
        """
        moment = now or datetime.now(UTC)
        report = DispatchReport()
        for row in await self._due(limit, moment):
            report.considered += 1
            await self._deliver(row, report, moment)
        return report

    async def _due(self, limit: int, moment: datetime) -> list[NotificationOutbox]:
        """Undelivered rows whose back-off has elapsed, oldest first."""
        naive = moment.replace(tzinfo=None)
        return list(
            await self.session.scalars(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.delivered_at.is_(None),
                    NotificationOutbox.attempts < MAX_ATTEMPTS,
                    (NotificationOutbox.next_attempt_at.is_(None))
                    | (NotificationOutbox.next_attempt_at <= naive),
                )
                .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
                .limit(limit)
            )
        )

    async def _deliver(self, row: NotificationOutbox, report: DispatchReport, moment: datetime) -> None:
        devices = await self.recipients.devices_for(row.recipient_kind, row.recipient_id)

        if self.projects is None:
            # No sender - push is off for this environment, or this is a dry run. Report
            # what would have happened and write **nothing**: a dry run that settles rows
            # is not a dry run, and a disabled deployment must keep its backlog so that
            # turning FCM on later delivers it rather than skipping it.
            if devices:
                report.retrying += 1
            else:
                report.no_devices += 1
            return

        if not devices:
            # Settled, not retried: there is nobody signed in to push to, and the in-app
            # list already carries the row for whenever they next open the app.
            row.delivered_at = moment.replace(tzinfo=None)
            row.last_error = "no registered device"
            await self.session.commit()
            report.no_devices += 1
            return

        message = _message(row)
        sent = 0
        failed = 0
        # Devices whose app has no Firebase credential. Counted apart from `failed`
        # because nothing was attempted for them - see the settle rule below.
        skipped = 0
        last_error: str | None = None
        for device in devices:
            # Routed by the app that registered the token, not by who the notification is
            # for: the same person signed into two apps has two tokens in two projects.
            client = self.projects.client_for(device.channel)
            if client is None:
                # That app's push is not configured yet.
                report.unconfigured += 1
                skipped += 1
                last_error = f"{device.channel or 'unknown'}: push not configured"
                continue
            result = await client.send(device.token, message)
            if result.ok:
                sent += 1
                continue
            failed += 1
            last_error = result.error
            if result.misrouted:
                # A working token sent through the wrong project. The token is kept - the
                # configuration is what is wrong - and the row retries so that fixing it
                # delivers the backlog.
                report.misrouted += 1
                logger.warning(
                    "Token registered on %s was rejected by project %s: check the credential mapping",
                    device.channel,
                    client.credentials.project_id,
                )
            elif result.token_dead:
                await self.recipients.forget(device.token)
                report.tokens_forgotten += 1
                # A dead token is not a reason to retry the notification; the others may
                # well have gone through, and this device will never accept it.
                failed -= 1

        attempted = len(devices) - skipped
        if sent or (attempted and failed == 0):
            # Settled when at least one device has it, or when every device that was
            # actually tried turned out to be a retired token - there is nobody left to
            # reach either way.
            #
            # `attempted` is what stops a row being settled when nothing was sent at all:
            # with no credential configured for any of the recipient's apps, `sent` and
            # `failed` are both zero, and settling on that alone would silently drop the
            # notification the moment a credential path was wrong.
            row.delivered_at = moment.replace(tzinfo=None)
            row.last_error = last_error
            report.delivered += 1
        else:
            self._schedule_retry(row, last_error, moment)
            if row.attempts >= MAX_ATTEMPTS:
                report.abandoned += 1
            else:
                report.retrying += 1
        await self.session.commit()

    @staticmethod
    def _schedule_retry(row: NotificationOutbox, error: str | None, moment: datetime) -> None:
        row.attempts = (row.attempts or 0) + 1
        row.last_error = (error or "unknown")[:255]
        if row.attempts >= MAX_ATTEMPTS:
            # Left undelivered on purpose. It is visible in the table with its last error
            # rather than silently marked done, which is what an operator needs to see.
            row.next_attempt_at = None
            logger.warning(
                "Notification %s abandoned after %s attempts: %s", row.id, row.attempts, row.last_error
            )
            return
        delay = RETRY_DELAYS[min(row.attempts - 1, len(RETRY_DELAYS) - 1)]
        row.next_attempt_at = (moment + delay).replace(tzinfo=None)


def _message(row: NotificationOutbox) -> PushMessage:
    """The FCM payload for one queued event.

    `data` carries the deep link. The app routes on `referenceType` + `referenceId` rather
    than parsing the title, so rewording a notification never breaks the tap target.
    """
    reference = reference_of(row.entity_type)
    data = {
        "notificationId": row.id,
        "eventType": row.event_type,
        "category": category_of(row.event_type, row.entity_type).value,
        "severity": row.severity or "INFO",
    }
    if reference and row.entity_id:
        data["referenceType"] = reference.value
        data["referenceId"] = row.entity_id
    return PushMessage(title=row.title, body=row.body, data=data)
