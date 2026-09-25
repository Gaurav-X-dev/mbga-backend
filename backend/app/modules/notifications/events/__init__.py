"""Every notification the platform can send, in one place, organised by domain.

Before this package the message text lived wherever the event happened to be queued - two
KYC events in `shared/notifications/outbox.py`, three order events in
`modules/orders/notifications.py` - so nobody could answer "what does this system actually
notify people about" without grepping. A catalogue answers that in one directory listing.

    customers.py    registration, KYC decisions
    orders.py       placed, confirmed, preparing, cancelled
    pricing.py      rate changes, per-customer prices
    deliveries.py   dispatch, delivered, failed, and the driver's own assignments
    payments.py     payment recorded, invoice due    (awaiting the payment module)
    stock.py        low stock, out of stock
    tasks.py        assigned, updated, completed, mentioned

A business module imports the builder it needs and hands the result to
`NotificationOutboxWriter.queue()` on its own transaction. It never writes message text
itself, so rewording a notification is a change in one file and never a change in a service.

Three rules every builder here keeps, which the catalogue test enforces:

* it sets `entity_type` **and** `entity_id`, so the row records what it is about and the app
  can deep-link it;
* its `entity_type` is one the category map knows, so it never renders as SYSTEM by accident;
* its `event_type` is unique across the catalogue, because that is what the outbox's
  uniqueness constraint keys on.
"""

from app.modules.notifications.events import (
    customers,
    deliveries,
    orders,
    payments,
    pricing,
    stock,
    tasks,
)
from app.modules.notifications.events._base import NotificationEvent

#: Every domain module, for the catalogue test and for anything that wants to enumerate
#: what the system can send.
DOMAINS = (customers, orders, pricing, deliveries, payments, stock, tasks)

__all__ = [
    "DOMAINS",
    "NotificationEvent",
    "customers",
    "deliveries",
    "orders",
    "payments",
    "pricing",
    "stock",
    "tasks",
]
