"""Warehouse vocabulary: buckets, movement types and what each type may touch (spec §11, §18.6).

Three buckets hold every cylinder a godown has: `filled` is sellable, `empty` is waiting to
go back to BPCL, `damaged` is out of service. A cylinder never leaves the warehouse by being
deleted - it moves from one bucket to another, or out through a movement that says where it
went. That is what makes the ledger reconcilable: counts and movements must always agree
(spec §18.6), so every count change is a `StockMovement` and nothing edits a count directly.

The cylinder **types** are not redefined here. They are
`app.modules.pricing.constants.CylinderType`, the same enum the rate card and order lines are
keyed on - a cylinder the warehouse cannot name is one an order cannot be filled from.
Labels come from `orders.constants.ORDER_LABELS` ("19 KG"), because the warehouse screen and
an order line name the same thing the same way.
"""

from enum import StrEnum

from app.modules.pricing.constants import CylinderType


class StockBucket(StrEnum):
    """Spec §2 `StockBucket`. Lower case on the wire, matching the spec's payloads."""

    FILLED = "filled"
    EMPTY = "empty"
    DAMAGED = "damaged"


class StockMovementType(StrEnum):
    """Spec §2 `StockMovementType`."""

    RECEIVED_FILLED = "RECEIVED_FILLED"
    SENT_TO_PLANT = "SENT_TO_PLANT"
    MARKED_DAMAGED = "MARKED_DAMAGED"
    CORRECTION = "CORRECTION"
    DISPATCHED = "DISPATCHED"
    EMPTIES_COLLECTED = "EMPTIES_COLLECTED"


class MovementReference(StrEnum):
    """What a movement points at (spec §3.13 `referenceType`)."""

    ORDER = "ORDER"
    DELIVERY = "DELIVERY"
    CHALLAN = "CHALLAN"


#: The four a staff member may post (spec §11.3). Anything else on that endpoint is refused.
MANUAL_TYPES: frozenset[StockMovementType] = frozenset(
    {
        StockMovementType.RECEIVED_FILLED,
        StockMovementType.SENT_TO_PLANT,
        StockMovementType.MARKED_DAMAGED,
        StockMovementType.CORRECTION,
    }
)

#: Written by the delivery endpoints, never by a person: a dispatch takes filled stock out
#: and a confirmed delivery brings empties back. Accepting these from the app would let a
#: count move without a delivery behind it, and the ledger would stop reconciling.
SYSTEM_TYPES: frozenset[StockMovementType] = frozenset(
    {StockMovementType.DISPATCHED, StockMovementType.EMPTIES_COLLECTED}
)

#: Which buckets `fromBucket` may name, per type (spec §11.3).
#:
#: `SENT_TO_PLANT` returns empties and write-offs to BPCL, so filled stock is not a legal
#: source - sending a full cylinder back is a dispatch, not a plant return. `MARKED_DAMAGED`
#: can condemn either a filled or an empty cylinder, but not one already damaged.
FROM_BUCKETS: dict[StockMovementType, tuple[StockBucket, ...]] = {
    StockMovementType.SENT_TO_PLANT: (StockBucket.EMPTY, StockBucket.DAMAGED),
    StockMovementType.MARKED_DAMAGED: (StockBucket.FILLED, StockBucket.EMPTY),
}

#: Types that require `quantity` (spec §11.3: "for first three types"). A correction carries
#: a `newCount` instead, and its quantity is derived from how far the count moved.
QUANTITY_TYPES: frozenset[StockMovementType] = frozenset(
    {
        StockMovementType.RECEIVED_FILLED,
        StockMovementType.SENT_TO_PLANT,
        StockMovementType.MARKED_DAMAGED,
    }
)

#: Spec §11.3's `quantity` error, "Enter at least 1". There is deliberately **no** business cap
#: above it: the spec's "Max 94" was illustrative, and a real refill truck of 5 KG cylinders
#: carries several hundred. Capping a movement at a number somebody once wrote in a document
#: means a godown that genuinely received 300 cylinders has to fake four movements to record it,
#: and the ledger stops matching the challan it came in on.
MIN_MOVEMENT_QUANTITY = 1

#: The only ceiling left, and it is about storage rather than business: a bucket has to stay
#: inside a 32-bit integer, and an unbounded quantity is how a slipped keypress becomes a stock
#: level nobody can explain. A correction's `newCount` is held to the same figure.
MAX_BUCKET_COUNT = 99_999

#: Reorder thresholds from spec §11.1, used when a merchant first stocks a cylinder type.
#: There is no endpoint to change these - §11 has three routes and none of them sets a
#: threshold - so a deployment tunes them in `stock_items` directly.
DEFAULT_REORDER_THRESHOLDS: dict[CylinderType, int] = {
    CylinderType.LPG_5KG: 150,
    CylinderType.LPG_19KG: 120,
    CylinderType.LPG_47_5KG_L: 50,
    CylinderType.LPG_47_5KG_V: 40,
    CylinderType.LPG_422KG_HIPPO: 4,
}

#: How many damaged cylinders make a pile worth mentioning (spec §11.1: "damaged >= 5 -> INFO").
DAMAGED_ALERT_FLOOR = 5

#: `ALL` on the movement filter means no cylinder filter (spec §11.2).
ALL_CYLINDERS = "ALL"

#: Default and ceiling for `limit` on the movement history. The screen shows a scrolling
#: ledger rather than pages, so the cap is a safety bound: a godown that has been running for
#: two years has tens of thousands of movements and no phone renders them.
DEFAULT_MOVEMENT_LIMIT = 50
MAX_MOVEMENT_LIMIT = 200
