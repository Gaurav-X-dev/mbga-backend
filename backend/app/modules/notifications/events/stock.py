"""Stock notifications (spec §18.8, "Stock below threshold").

Queued by `modules.inventory.service` when a movement takes filled stock **across** the
reorder line - not while it is merely below it. A warning on every movement during a shortage
is muted within a day, and then the one that matters is muted too.

Spec §18.8 marks this CRITICAL/WARNING, and the split here is the one that matters
operationally: below the reorder threshold is a plan-a-refill warning; actually empty is
critical, because orders for that cylinder cannot be filled at all.

Both builders take an optional `movement_id`, which is what makes them repeatable. The outbox
is unique on `(event_type, entity_type, entity_id, recipient_kind, recipient_id)`, so keying on
the cylinder type alone would let a cylinder warn once and then never again - September's
shortage would silently suppress November's. Keying on the movement that crossed the line gives
exactly one notification per crossing, for ever. The parameter is appended rather than inserted
so existing positional calls keep working.
"""

from app.modules.notifications.events._base import (
    CRITICAL,
    MERCHANT,
    STOCK,
    WARNING,
    NotificationEvent,
)


def below_threshold(
    merchant_id: str,
    cylinder_type: str,
    cylinder_label: str,
    count: int,
    threshold: int,
    movement_id: str | None = None,
) -> NotificationEvent:
    """To staff: plan a BPCL refill."""
    return NotificationEvent(
        event_type="STOCK_BELOW_THRESHOLD",
        recipient_kind=MERCHANT,
        # Keyed on the movement that crossed the line when there is one, so the same cylinder
        # can warn again next month. Falling back to the cylinder type keeps a caller that has
        # no movement to point at - a nightly sweep, say - from writing a row with no key.
        entity_type=STOCK,
        entity_id=movement_id or cylinder_type,
        recipient_id=merchant_id,
        title="Stock below reorder threshold",
        body=f"{cylinder_label} filled stock is {count} against a threshold of {threshold}. Plan a BPCL refill.",
        severity=WARNING,
    )


def out_of_stock(
    merchant_id: str, cylinder_type: str, cylinder_label: str, movement_id: str | None = None
) -> NotificationEvent:
    """To staff: orders for this cylinder cannot be filled."""
    return NotificationEvent(
        event_type="STOCK_OUT",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=STOCK,
        entity_id=movement_id or cylinder_type,
        title="Out of stock",
        body=f"{cylinder_label} filled stock is zero. Orders for it cannot be delivered.",
        severity=CRITICAL,
    )
