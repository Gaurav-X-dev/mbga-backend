"""Pricing notifications.

Not in spec §18.8's table, and deliberately added: a price is the one thing in this system
that changes what everybody else's numbers mean. Two audiences care.

**Staff**, when a rate moves mid-month. The Standard tab is edited by whoever holds
`pricing.manage`, but the salesperson quoting a customer on the phone is working from what
they last saw. A silent change is how a customer is quoted one figure and billed another.

**A customer**, when *their own* price is set or removed. That is a commitment somebody made
to them, and they should not discover it on an invoice.

Both are keyed on the entity they are about, so the notification deep-links to the screen
that explains it.
"""

from app.modules.notifications.events._base import (
    CUSTOMER,
    INFO,
    MERCHANT,
    PRICING,
    WARNING,
    NotificationEvent,
    rupees,
)

# A price change is a **repeatable** event: the same cylinder, in the same month, for the
# same merchant, legitimately moves more than once. The outbox is uniquely keyed on
# (event_type, entity_type, entity_id, recipient_kind, recipient_id) so that a retry of the
# same event collapses - which means a repeatable event has to identify the *occurrence*,
# not the subject. Each builder below is therefore keyed on the log row the change wrote:
# unique per change, and it points at the exact audit entry that explains the message.


def rate_changed(
    merchant_id: str,
    change_log_id: str,
    cylinder_label: str,
    old_price: int | None,
    new_price: int,
    changed_by: str,
    reason: str | None = None,
) -> NotificationEvent:
    """To staff: a rate moved, and who moved it.

    WARNING rather than INFO: anyone mid-conversation with a customer needs to know before
    they quote the old figure.
    """
    movement = f"{rupees(old_price)} to {rupees(new_price)}" if old_price is not None else rupees(new_price)
    tail = f" {reason}" if reason else ""
    return NotificationEvent(
        event_type="pricing.rate_changed",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=PRICING,
        entity_id=change_log_id,
        title="Price updated",
        body=f"{cylinder_label} changed from {movement} by {changed_by}.{tail}",
        severity=WARNING,
    )


def customer_price_set(
    customer_id: str,
    change_log_id: str,
    cylinder_label: str,
    price: int,
    set_by: str,
    reason: str | None = None,
) -> NotificationEvent:
    """To the customer: you have your own rate for this cylinder now."""
    tail = f" {reason}" if reason else ""
    return NotificationEvent(
        event_type="pricing.customer_price_set",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=PRICING,
        entity_id=change_log_id,
        title="Your price has been updated",
        body=f"{cylinder_label} is now {rupees(price)} for you, set by {set_by}.{tail}",
        severity=INFO,
    )


def customer_price_removed(
    customer_id: str, change_log_id: str, cylinder_label: str, standard_price: int | None, removed_by: str
) -> NotificationEvent:
    """To the customer: you are back on the standard rate."""
    now = f" It is now {rupees(standard_price)}." if standard_price is not None else ""
    return NotificationEvent(
        event_type="pricing.customer_price_removed",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=PRICING,
        entity_id=change_log_id,
        title="Your special price was removed",
        body=f"{cylinder_label} is back on the standard rate, changed by {removed_by}.{now}",
        severity=WARNING,
    )
