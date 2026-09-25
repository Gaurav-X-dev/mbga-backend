"""Order vocabulary: the status catalogue, cylinder limits and display labels (spec §6, §18.3).

The cylinder **types** are not redefined here. They are
`app.modules.pricing.constants.CylinderType` - the same enum the price card is keyed on -
because an order line that cannot be priced is not an order line. What is defined here is
what belongs to ordering: how many of each may go on a line, and how each reads on an order.

Two label sets, deliberately. Pricing's `CYLINDER_LABELS` ("5 KG Cylinder") names a row in a
rate card; an order line says "5 KG" (spec §3.9) and the one-line summary says "47.5 L"
(spec §3.10). Same five types, three screens, three phrasings - so the labels live with the
screen that shows them rather than being forced into one string that reads badly everywhere.
"""

from enum import StrEnum

from app.modules.pricing.constants import CylinderType


class OrderStatus(StrEnum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    # There is no PREPARING. It meant "cylinders are being allocated at the godown", which is a
    # step nobody worked in: allocating the cylinders *is* dispatching the van. A confirmed order
    # goes straight out for delivery when its slip is dispatched.
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderMode(StrEnum):
    NEW = "NEW"
    REPEAT = "REPEAT"


class OrderSource(StrEnum):
    CUSTOMER_APP = "CUSTOMER_APP"
    MERCHANT_APP = "MERCHANT_APP"


class StatusTone(StrEnum):
    """Colour hint for the status chip (spec §2 `StatusTone`)."""

    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    PENDING = "pending"
    NEUTRAL = "neutral"


class StatusMeta:
    """One row of the catalogue `GET /orders/statuses` returns."""

    __slots__ = ("code", "description", "is_terminal", "label", "sequence", "tone")

    def __init__(self, code: OrderStatus, label: str, sequence: int, tone: StatusTone, description: str, is_terminal: bool) -> None:
        self.code = code
        self.label = label
        self.sequence = sequence
        self.tone = tone
        self.description = description
        self.is_terminal = is_terminal


# Spec §6.1, verbatim. The apps render their timeline from this and hard-code no transitions,
# so this table - not the app - is what a new status has to be added to.
STATUS_CATALOGUE: tuple[StatusMeta, ...] = (
    StatusMeta(OrderStatus.PLACED, "Order Placed", 1, StatusTone.INFO, "We have received your order.", False),
    StatusMeta(OrderStatus.CONFIRMED, "Confirmed", 2, StatusTone.INFO, "Confirmed and scheduled for delivery.", False),
    StatusMeta(OrderStatus.OUT_FOR_DELIVERY, "Out for Delivery", 3, StatusTone.WARNING, "Your cylinders are on the way.", False),
    StatusMeta(OrderStatus.DELIVERED, "Delivered", 4, StatusTone.SUCCESS, "Delivered and confirmed.", True),
    # 99 keeps terminal failure states out of the timeline's numbered progression.
    StatusMeta(OrderStatus.CANCELLED, "Cancelled", 99, StatusTone.ERROR, "This order was cancelled.", True),
)

STATUS_BY_CODE: dict[str, StatusMeta] = {meta.code.value: meta for meta in STATUS_CATALOGUE}

#: `status=ACTIVE` on the list endpoint means every non-terminal status (spec §6.5).
ACTIVE_STATUSES: tuple[str, ...] = tuple(meta.code.value for meta in STATUS_CATALOGUE if not meta.is_terminal)
TERMINAL_STATUSES: frozenset[str] = frozenset(meta.code.value for meta in STATUS_CATALOGUE if meta.is_terminal)

#: The filter word meaning "do not filter by status".
ALL_STATUSES = "ALL"
ACTIVE_FILTER = "ACTIVE"

# Which moves are legal. Ordering is forward-only along the timeline; anything not terminal
# may still be cancelled. Held here rather than in the service so the rule is readable and
# testable on its own.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatus.PLACED.value: frozenset({OrderStatus.CONFIRMED.value, OrderStatus.CANCELLED.value}),
    # Straight onto the van: dispatching the slip is the only thing that moves it, and that
    # happens the moment the cylinders are loaded.
    OrderStatus.CONFIRMED.value: frozenset(
        {OrderStatus.OUT_FOR_DELIVERY.value, OrderStatus.CANCELLED.value}
    ),
    # Once it is on the van, cancelling is a delivery failure, not an order cancellation.
    OrderStatus.OUT_FOR_DELIVERY.value: frozenset({OrderStatus.DELIVERED.value}),
    OrderStatus.DELIVERED.value: frozenset(),
    OrderStatus.CANCELLED.value: frozenset(),
}


# --- Cylinders on an order ------------------------------------------------------------------

#: How an order line names its cylinder (spec §3.9 / §18.3).
ORDER_LABELS: dict[CylinderType, str] = {
    CylinderType.LPG_5KG: "5 KG",
    CylinderType.LPG_19KG: "19 KG",
    CylinderType.LPG_47_5KG_L: "47.5 KG L",
    CylinderType.LPG_47_5KG_V: "47.5 KG V",
    CylinderType.LPG_422KG_HIPPO: "422 KG Hippo",
}

#: The shorter form used inside `itemsSummary` - "6 × 47.5 L · 2 × 47.5 V" (spec §3.10).
SUMMARY_LABELS: dict[CylinderType, str] = {
    CylinderType.LPG_5KG: "5 KG",
    CylinderType.LPG_19KG: "19 KG",
    CylinderType.LPG_47_5KG_L: "47.5 L",
    CylinderType.LPG_47_5KG_V: "47.5 V",
    CylinderType.LPG_422KG_HIPPO: "422 Hippo",
}

#: Per-line quantity limits (spec §18.3). A whole order may carry several lines.
QUANTITY_LIMITS: dict[CylinderType, tuple[int, int]] = {
    CylinderType.LPG_5KG: (1, 100),
    CylinderType.LPG_19KG: (1, 50),
    CylinderType.LPG_47_5KG_L: (1, 30),
    CylinderType.LPG_47_5KG_V: (1, 30),
    CylinderType.LPG_422KG_HIPPO: (1, 5),
}

#: How many distinct lines one order may carry. Five types exist, so anything above that is
#: a malformed body rather than a large order.
MAX_ORDER_LINES = len(CylinderType)

#: Shown when an order has no delivery site (spec §3.10 `deliverySiteName`).
REGISTERED_ADDRESS_LABEL = "Registered delivery address"
