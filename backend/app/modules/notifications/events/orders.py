"""Order notifications (spec §18.8, "Order created").

Every event here is keyed on the **order id**, so tapping the notification opens that order
and a support query can be traced from the message back to the row.

Who hears what, and why:

* The **customer** hears about their own order changing state - they placed it and are
  waiting for it.
* The **merchant** hears about work arriving or disappearing - a new order needs confirming,
  a cancellation frees a slot on the van. Both are WARNING rather than INFO because somebody
  has to do something about them; an order nobody confirms is an order nobody delivers.
"""

from app.modules.notifications.events._base import (
    CUSTOMER,
    INFO,
    MERCHANT,
    ORDER,
    WARNING,
    NotificationEvent,
    rupees,
)


def order_placed_customer(customer_id: str, order_id: str, order_number: str, total: int) -> NotificationEvent:
    """To the customer: we have your order."""
    return NotificationEvent(
        event_type="ORDER_PLACED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order placed",
        body=f"Order {order_number} for {rupees(total)} has been placed.",
        severity=INFO,
    )


def order_placed_merchant(
    merchant_id: str, order_id: str, order_number: str, customer_name: str
) -> NotificationEvent:
    """To the merchant: work has arrived."""
    return NotificationEvent(
        event_type="ORDER_RECEIVED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="New order received",
        body=f"Order {order_number} from {customer_name or 'a customer'} needs confirming.",
        severity=WARNING,
    )


def order_cancelled_customer(customer_id: str, order_id: str, order_number: str) -> NotificationEvent:
    """To the customer: it is off."""
    return NotificationEvent(
        event_type="ORDER_CANCELLED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order cancelled",
        body=f"Order {order_number} has been cancelled.",
        severity=WARNING,
    )


def order_cancelled_merchant(
    merchant_id: str, order_id: str, order_number: str, customer_name: str, reason: str | None = None
) -> NotificationEvent:
    """To the merchant: stop preparing it.

    Staff need this as much as the customer does. Without it the godown keeps a cancelled
    order on the loading list and the cylinders go out anyway.
    """
    tail = f" Reason: {reason}" if reason else ""
    return NotificationEvent(
        event_type="ORDER_CANCELLED_MERCHANT",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order cancelled",
        body=f"Order {order_number} from {customer_name or 'a customer'} was cancelled.{tail}",
        severity=WARNING,
    )


def order_confirmed(
    customer_id: str, order_id: str, order_number: str, delivery_date: str | None = None
) -> NotificationEvent:
    """To the customer: the merchant has accepted it, and when it is coming.

    The date, not a slot. The platform used to promise a morning or afternoon window; it does not
    any more, because the godown never scheduled against one - see `orders/cutoff.py`.
    """
    when = f" Expected delivery: {delivery_date}." if delivery_date else ""
    return NotificationEvent(
        event_type="ORDER_CONFIRMED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order confirmed",
        body=f"Order {order_number} is confirmed and scheduled for delivery.{when}",
        severity=INFO,
    )

