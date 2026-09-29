"""Payment and invoice notifications (spec §18.8, "Payment recorded").

**No module calls these yet** - the payment slice is not merged. See the note in
`deliveries.py`; the same reasoning applies.

Keyed on the payment or invoice, so the notification opens the receipt rather than a list.
"""

from app.modules.notifications.events._base import (
    CRITICAL,
    CUSTOMER,
    INFO,
    INVOICE,
    MERCHANT,
    PAYMENT,
    WARNING,
    NotificationEvent,
    rupees,
)


def payment_recorded(
    customer_id: str, payment_id: str, amount: int, mode: str, balance: int | None = None
) -> NotificationEvent:
    """To the customer: your payment is on the books."""
    outstanding = f" Outstanding balance: {rupees(balance)}." if balance is not None else ""
    return NotificationEvent(
        event_type="PAYMENT_RECORDED",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=PAYMENT,
        entity_id=payment_id,
        title="Payment received",
        body=f"{rupees(amount)} received by {mode}.{outstanding}",
        severity=INFO,
    )


def payment_invalid(merchant_id: str, payment_id: str, amount: int, reason: str) -> NotificationEvent:
    """To staff: a payment failed reconciliation and the money is not there.

    CRITICAL because an unreconciled payment means an order may have been released against
    money that never arrived.
    """
    return NotificationEvent(
        event_type="PAYMENT_INVALID",
        recipient_kind=MERCHANT,
        recipient_id=merchant_id,
        entity_type=PAYMENT,
        entity_id=payment_id,
        title="Payment could not be reconciled",
        body=f"{rupees(amount)} failed reconciliation. {reason}",
        severity=CRITICAL,
    )


def invoice_overdue(customer_id: str, invoice_id: str, invoice_number: str, amount: int, days: int) -> NotificationEvent:
    """To the customer: this one is late."""
    return NotificationEvent(
        event_type="INVOICE_OVERDUE",
        recipient_kind=CUSTOMER,
        recipient_id=customer_id,
        entity_type=INVOICE,
        entity_id=invoice_id,
        title="Invoice overdue",
        body=f"Invoice {invoice_number} for {rupees(amount)} is {days} day(s) overdue.",
        severity=WARNING,
    )
