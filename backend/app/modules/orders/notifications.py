"""Order notification builders.

Moved to `app.modules.notifications.events.orders` when the catalogue was introduced, and
re-exported here so the order service keeps its existing import. New code should import
from the catalogue.
"""

from app.modules.notifications.events.orders import (
    order_cancelled_customer,
    order_cancelled_merchant,
    order_confirmed,
    order_placed_customer,
    order_placed_merchant,
)

#: The old name, kept so nothing that already imports it breaks.
order_cancelled = order_cancelled_customer

__all__ = [
    "order_cancelled",
    "order_cancelled_customer",
    "order_cancelled_merchant",
    "order_confirmed",
    "order_placed_customer",
    "order_placed_merchant",
]
