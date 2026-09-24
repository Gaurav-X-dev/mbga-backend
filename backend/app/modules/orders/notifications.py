"""Order notification events (spec §18.8).

Nothing here sends anything. Each builder returns an event the service queues on its own
transaction, so an order that rolls back cannot leave "Order placed" behind and a committed
order always has its message waiting.

Titles and bodies carry the order number and the amount - both already visible to the
recipient - and never a mobile number, a document number or an internal id.
"""

from app.shared.notifications.outbox import NotificationEvent, Severity

ORDER = "order"
CUSTOMER = "customer"
MERCHANT = "merchant"


def order_placed_customer(customer_id: str, order_id: str, order_number: str, total: int) -> NotificationEvent:
    return NotificationEvent(
        event_type="ORDER_PLACED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order placed",
        body=f"Order {order_number} for ₹{total:,} has been placed.",
        severity=Severity.INFO,
    )


def order_placed_merchant(merchant_id: str, order_id: str, order_number: str, customer_name: str) -> NotificationEvent:
    return NotificationEvent(
        event_type="ORDER_RECEIVED",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=ORDER,
        entity_id=order_id,
        # WARNING per spec §18.8: a new order needs someone to act on it, so it should not
        # sit at the same weight as an informational message.
        title="New order received",
        body=f"Order {order_number} from {customer_name or 'a customer'} needs confirming.",
        severity=Severity.WARNING,
    )


def order_cancelled(customer_id: str, order_id: str, order_number: str) -> NotificationEvent:
    return NotificationEvent(
        event_type="ORDER_CANCELLED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=ORDER,
        entity_id=order_id,
        title="Order cancelled",
        body=f"Order {order_number} has been cancelled.",
        severity=Severity.WARNING,
    )
