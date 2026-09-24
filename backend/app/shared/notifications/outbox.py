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

from sqlalchemy.ext.asyncio import AsyncSession

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
        """
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


# --- Customer and KYC events (spec §18.8) ---------------------------------------------------
#
# Every event below is keyed on the **application** id, not the customer id. A customer who
# was rejected and resubmitted legitimately generates a second "Application received" and a
# second decision, and keying on the customer would make the outbox's uniqueness constraint
# swallow them. Keying on the application still collapses retries of the *same* submit,
# which is what that constraint is for.

APPLICATION = "kyc_application"


def application_received(customer_id: str, business_name: str, application_id: str) -> NotificationEvent:
    return NotificationEvent(
        event_type="customer.application_received",
        recipient_kind="customer",
        recipient_id=customer_id,
        entity_type=APPLICATION,
        entity_id=application_id,
        title="Application received",
        body=f"We have received the registration for {business_name} and it is now under review.",
    )


def new_kyc_application(
    merchant_id: str, application_id: str, business_name: str, added_by: str | None = None
) -> NotificationEvent:
    body = f"{business_name} is awaiting KYC review."
    if added_by:
        body = f"{business_name} was added by {added_by} and is awaiting KYC review."
    return NotificationEvent(
        event_type="kyc.application_submitted",
        recipient_kind="merchant",
        recipient_id=merchant_id,
        entity_type=APPLICATION,
        entity_id=application_id,
        title="New KYC application",
        body=body,
    )


def account_approved(customer_id: str, business_name: str, application_id: str) -> NotificationEvent:
    return NotificationEvent(
        event_type="customer.approved",
        recipient_kind="customer",
        recipient_id=customer_id,
        entity_type=APPLICATION,
        entity_id=application_id,
        title="Account approved",
        body=f"{business_name} is approved. You can now sign in and place orders.",
    )


def application_rejected(customer_id: str, business_name: str, reason: str, application_id: str) -> NotificationEvent:
    return NotificationEvent(
        event_type="customer.rejected",
        recipient_kind="customer",
        recipient_id=customer_id,
        entity_type=APPLICATION,
        entity_id=application_id,
        title="Application rejected",
        body=f"The registration for {business_name} was not approved. Reason: {reason}",
        severity=Severity.CRITICAL,
    )
