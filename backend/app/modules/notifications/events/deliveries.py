"""Delivery notifications (spec §18.8, rows "Dispatch" and "Delivery confirmed").

**No module calls these yet.** The delivery slice is not merged, so they are a catalogue
entry rather than live behaviour - written now because the spec fixes the wording and the
audience, and because a delivery module should not have to invent message text on its way
in. When it lands, each of these is one line at the point the status moves.

The two audiences here are keyed differently, on purpose:

* what the **customer** is told is keyed on the **order** - that is the screen they have
  open and the id they would quote on the phone;
* what the **driver** is told is keyed on the **delivery** - the trip is what they act on,
  and a job handed to one driver, taken back and handed out again is a new trip. Keying a
  driver's events on the order instead would collide on the outbox's uniqueness constraint
  the second time round, and the reassignment would silently never arrive.
"""

from app.modules.notifications.events._base import (
    CRITICAL,
    CUSTOMER,
    DELIVERY,
    INFO,
    MERCHANT,
    ORDER,
    USER,
    WARNING,
    NotificationEvent,
)


def out_for_delivery(
    customer_id: str,
    order_id: str,
    order_number: str,
    driver_name: str | None = None,
    confirmation_code: str | None = None,
) -> NotificationEvent:
    """To the customer: it is on the van, and here is the code for the driver.

    This notification is the **only** channel that tells the customer their confirmation code, so
    the code has to be in the body. Without it the driver would arrive asking for four digits
    nobody had ever sent - and the code parameter is appended rather than inserted so existing
    positional calls keep working.
    """
    who = f" {driver_name} is on the way." if driver_name else ""
    code = f" Share code {confirmation_code} with the driver." if confirmation_code else ""
    return NotificationEvent(
        event_type="DELIVERY_DISPATCHED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order out for delivery",
        body=f"Order {order_number} has left the godown.{who}{code}",
        severity=INFO,
    )


def delivered(
    customer_id: str, order_id: str, order_number: str, cylinders: int | None = None
) -> NotificationEvent:
    """To the customer: it arrived."""
    count = f" {cylinders} cylinder(s) delivered." if cylinders else ""
    return NotificationEvent(
        event_type="DELIVERY_COMPLETED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order delivered",
        body=f"Order {order_number} has been delivered.{count}",
        severity=INFO,
    )


# --- To the driver, on the delivery app ---------------------------------------------------
#
# Addressed to the person (`recipient_kind = "user"`), never to the merchant bucket: a job
# is one driver's to do, and the office does not need a copy of every assignment. This is
# also what routes the push through the `mbga-delivery-partner` Firebase project, because
# the driver's token was registered on the delivery channel.


def assigned_to_driver(
    driver_user_id: str,
    delivery_id: str,
    order_number: str,
    slot: str | None = None,
    customer_name: str | None = None,
) -> NotificationEvent:
    """To the driver: this trip is yours.

    INFO rather than WARNING even though it needs acting on. An assignment is the driver's
    ordinary work, and colouring every job as a warning would leave nothing to distinguish
    the trip that actually went wrong.
    """
    where = f" for {customer_name}" if customer_name else ""
    when = f" Slot: {slot}." if slot else ""
    return NotificationEvent(
        event_type="DELIVERY_ASSIGNED",
        recipient_kind=USER,
        recipient_id=driver_user_id,
        entity_type=DELIVERY,
        entity_id=delivery_id,
        title="New delivery assigned",
        body=f"Order {order_number}{where} has been assigned to you.{when}",
        severity=INFO,
    )


def unassigned_from_driver(
    driver_user_id: str, delivery_id: str, order_number: str, reason: str | None = None
) -> NotificationEvent:
    """To the driver: this trip is no longer yours.

    WARNING, because a driver acting on a stale job loads a van for a delivery somebody
    else is already making.
    """
    why = f" {reason}" if reason else ""
    return NotificationEvent(
        event_type="DELIVERY_UNASSIGNED",
        recipient_kind=USER,
        recipient_id=driver_user_id,
        entity_type=DELIVERY,
        entity_id=delivery_id,
        title="Delivery reassigned",
        body=f"Order {order_number} is no longer assigned to you.{why}",
        severity=WARNING,
    )


def cancelled_in_transit(
    driver_user_id: str, delivery_id: str, order_number: str, customer_name: str | None = None
) -> NotificationEvent:
    """To the driver: stop, the order is cancelled.

    CRITICAL because it is the one delivery notification that has to interrupt. The van may
    already be at the gate, and a cylinder handed over against a cancelled order has to be
    collected back and unwound in the books.
    """
    whose = f" for {customer_name}" if customer_name else ""
    return NotificationEvent(
        event_type="DELIVERY_ORDER_CANCELLED",
        recipient_kind=USER,
        recipient_id=driver_user_id,
        entity_type=DELIVERY,
        entity_id=delivery_id,
        title="Order cancelled - do not deliver",
        body=f"Order {order_number}{whose} was cancelled. Do not complete this delivery.",
        severity=CRITICAL,
    )


# --- To staff -----------------------------------------------------------------------------


def delivery_failed(
    merchant_id: str, order_id: str, order_number: str, reason: str | None = None
) -> NotificationEvent:
    """To staff: it came back. Somebody has to reschedule it.

    Addressed to the merchant, not the customer: a failed delivery needs an internal
    decision before the customer is told anything.
    """
    why = f" {reason}" if reason else ""
    return NotificationEvent(
        event_type="DELIVERY_FAILED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Delivery failed",
        body=f"Order {order_number} could not be delivered and needs rescheduling.{why}",
        severity=WARNING,
    )
