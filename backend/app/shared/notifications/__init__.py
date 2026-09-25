"""Business notification events, queued transactionally for later delivery.

This package is the **transport**: what an event is, and how it is written to the outbox
inside the caller's transaction.

The events themselves - every title, body, audience and severity the platform can send -
are the catalogue in `app.modules.notifications.events`, organised by domain. The customer
and KYC builders are re-exported here so the registration and review services keep their
existing imports; they are imported lazily, because the catalogue needs `NotificationEvent`
from this package and importing it eagerly here would close the circle.
"""

from typing import TYPE_CHECKING, Any

from app.shared.notifications.outbox import (
    NotificationEvent,
    NotificationOutboxWriter,
    Severity,
)

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from app.modules.notifications.events.customers import (
        account_approved,
        application_received,
        application_rejected,
        new_kyc_application,
    )

#: Builders that used to live here. Resolved on first use, not at import time.
_CATALOGUE = {
    "account_approved",
    "application_received",
    "application_rejected",
    "new_kyc_application",
}

__all__ = [
    "NotificationEvent",
    "NotificationOutboxWriter",
    "Severity",
    "account_approved",
    "application_received",
    "application_rejected",
    "new_kyc_application",
]


def __getattr__(name: str) -> Any:
    """Resolve a moved builder from the catalogue on first access.

    A module-level import would run while `app.modules.notifications.events` is still
    importing `NotificationEvent` from here, and whichever side was touched first would get
    a half-built module. Deferring it to attribute access breaks that without asking every
    existing caller to change its import.
    """
    if name in _CATALOGUE:
        from app.modules.notifications.events import customers

        return getattr(customers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
