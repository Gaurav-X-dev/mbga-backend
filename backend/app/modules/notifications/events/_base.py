"""Shared vocabulary for every notification the platform can send.

Each domain module in this package builds `NotificationEvent`s for one part of the system.
They share three things, which is why they are here rather than repeated six times:

* **`entity_type` / `entity_id`** — what the notification is *about*. This is what gets
  stored on the row and what the app deep-links on, so it is never left blank: a
  notification the user cannot act on is a notification they ignore.
* **Recipient kinds** — who it is addressed to. `merchant` is a shared bucket read by every
  staff member (spec §15); `customer` and `user` are one person.
* **Severity** — INFO is "for your records", WARNING is "someone needs to act", CRITICAL is
  "this blocks them". Used for the colour and, later, for whether to wake a phone.
"""

from app.modules.notifications.constants import RecipientKind, Severity
from app.shared.notifications.outbox import NotificationEvent

# Recipient kinds, re-exported so a domain module imports one thing.
CUSTOMER = RecipientKind.CUSTOMER.value
MERCHANT = RecipientKind.MERCHANT.value
USER = RecipientKind.USER.value

# Entity types. These drive `category` and `referenceType` through
# `notifications.constants`, so adding one here means adding it to those maps too.
ORDER = "order"
DELIVERY = "delivery"
PAYMENT = "payment"
INVOICE = "invoice"
CUSTOMER_ENTITY = "customer"
KYC_APPLICATION = "kyc_application"
PRICING = "pricing"
STOCK = "stock"
TASK = "task"

INFO = Severity.INFO.value
WARNING = Severity.WARNING.value
CRITICAL = Severity.CRITICAL.value

__all__ = [
    "CRITICAL",
    "CUSTOMER",
    "CUSTOMER_ENTITY",
    "DELIVERY",
    "INFO",
    "INVOICE",
    "KYC_APPLICATION",
    "MERCHANT",
    "ORDER",
    "PAYMENT",
    "PRICING",
    "STOCK",
    "TASK",
    "USER",
    "WARNING",
    "NotificationEvent",
]


def rupees(amount: int) -> str:
    """`34500` -> `"₹34,500"`. One formatter, so every message reads the same."""
    return f"₹{amount:,}"
