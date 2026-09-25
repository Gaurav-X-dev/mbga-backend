"""Customer account and KYC notifications (spec §18.8, rows 1 and 2).

Every event here is keyed on the **application** id, not the customer id. A customer who was
rejected and resubmitted legitimately generates a second "Application received" and a second
decision; keying on the customer would make the outbox's uniqueness constraint swallow the
repeat. Keying on the application still collapses retries of the *same* submit, which is
what that constraint is for.

A rejection is CRITICAL rather than WARNING: the account cannot be used until the customer
acts, so it should not sit at the same weight as a status update.
"""

from app.modules.notifications.events._base import (
    CRITICAL,
    CUSTOMER,
    INFO,
    KYC_APPLICATION,
    MERCHANT,
    WARNING,
    NotificationEvent,
)


def application_received(customer_id: str, business_name: str, application_id: str) -> NotificationEvent:
    """To the customer: we have your registration."""
    return NotificationEvent(
        event_type="customer.application_received",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=KYC_APPLICATION,
        entity_id=application_id,
        title="Application received",
        body=f"We have received the registration for {business_name}. You will hear from us once it is reviewed.",
        severity=INFO,
    )


def new_kyc_application(
    merchant_id: str, application_id: str, business_name: str, added_by: str | None = None
) -> NotificationEvent:
    """To the merchant: somebody is waiting on a decision.

    The argument order is the one the registration service has always called it with -
    `(merchant, application, business, added_by)`. It reads oddly next to the others, but
    reordering it to match would be a silent breakage: every argument is a string, so a
    swapped pair type-checks, runs, and puts the application id where the name should be.
    """
    body = f"{business_name} is awaiting KYC review."
    if added_by:
        body = f"{business_name} was added by {added_by} and is awaiting KYC review."
    return NotificationEvent(
        event_type="kyc.application_submitted",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=KYC_APPLICATION,
        entity_id=application_id,
        title="New KYC application",
        body=body,
        severity=WARNING,
    )


def account_approved(customer_id: str, business_name: str, application_id: str) -> NotificationEvent:
    """To the customer: you can order now."""
    return NotificationEvent(
        event_type="customer.approved",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=KYC_APPLICATION,
        entity_id=application_id,
        title="Account approved",
        body=f"{business_name} is approved. You can start placing orders.",
        severity=INFO,
    )


def application_rejected(
    customer_id: str, business_name: str, reason: str, application_id: str
) -> NotificationEvent:
    """To the customer: it is blocked, and here is what to fix."""
    return NotificationEvent(
        event_type="customer.rejected",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=KYC_APPLICATION,
        entity_id=application_id,
        title="Application rejected",
        # The reason is the whole point of the message - without it the customer has no
        # idea what to correct before resubmitting.
        body=f"The registration for {business_name} was rejected. {reason}",
        severity=CRITICAL,
    )
