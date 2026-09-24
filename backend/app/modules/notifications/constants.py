"""Notification vocabulary, and how a queued event becomes one the apps can render.

The outbox rows the business modules already write carry an `event_type` and an
`entity_type`; the apps need a `category` and a `referenceType` from §2 to colour the row
and to deep-link it. That translation lives here rather than in each writer, so adding an
event never means remembering to set four more fields correctly.

An event nobody has mapped still delivers - it falls back to SYSTEM with no deep link, which
shows the user a real message instead of dropping it because a lookup missed.
"""

from enum import StrEnum


class Category(StrEnum):
    """§2 `NotificationCategory`. Drives the icon and the filter chips."""

    ORDER = "ORDER"
    DELIVERY = "DELIVERY"
    PAYMENT = "PAYMENT"
    ACCOUNT = "ACCOUNT"
    STOCK = "STOCK"
    KYC = "KYC"
    PRICING = "PRICING"
    SYSTEM = "SYSTEM"


class ReferenceType(StrEnum):
    """§2 `ReferenceType`. What tapping the notification opens."""

    ORDER = "ORDER"
    PAYMENT = "PAYMENT"
    CUSTOMER = "CUSTOMER"
    DELIVERY = "DELIVERY"
    KYC = "KYC"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RecipientKind(StrEnum):
    """Who a queued event is addressed to.

    Spec §15: "Customers get their own bucket; all staff share the merchant bucket." So a
    merchant-addressed event is one row read by every staff member, not one row per person.
    """

    CUSTOMER = "customer"
    MERCHANT = "merchant"
    USER = "user"


# Event type -> category. Checked first, because the same entity means different things to
# the two audiences: a KYC decision is the customer's ACCOUNT and the merchant's KYC queue.
EVENT_CATEGORIES: dict[str, Category] = {
    "ORDER_PLACED": Category.ORDER,
    "ORDER_RECEIVED": Category.ORDER,
    "ORDER_CANCELLED": Category.ORDER,
    "customer.application_received": Category.ACCOUNT,
    "customer.approved": Category.ACCOUNT,
    "customer.rejected": Category.ACCOUNT,
    "kyc.application_submitted": Category.KYC,
}

# Fallback when the event is not mapped above.
ENTITY_CATEGORIES: dict[str, Category] = {
    "order": Category.ORDER,
    "kyc_application": Category.KYC,
    "customer": Category.ACCOUNT,
    "payment": Category.PAYMENT,
    "delivery": Category.DELIVERY,
    "stock": Category.STOCK,
    "pricing": Category.PRICING,
}

# What the row deep-links to. Absent means the app shows it without a tap target rather
# than opening a screen that cannot resolve the id.
ENTITY_REFERENCES: dict[str, ReferenceType] = {
    "order": ReferenceType.ORDER,
    "kyc_application": ReferenceType.KYC,
    "customer": ReferenceType.CUSTOMER,
    "payment": ReferenceType.PAYMENT,
    "delivery": ReferenceType.DELIVERY,
}


def category_of(event_type: str, entity_type: str | None) -> Category:
    mapped = EVENT_CATEGORIES.get(event_type)
    if mapped is not None:
        return mapped
    return ENTITY_CATEGORIES.get((entity_type or "").lower(), Category.SYSTEM)


def reference_of(entity_type: str | None) -> ReferenceType | None:
    return ENTITY_REFERENCES.get((entity_type or "").lower())
