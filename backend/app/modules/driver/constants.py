"""Vocabulary for the delivery app's own screens.

The driver sees a narrower world than the dispatch board does. They get the slips addressed to
them, in the order they have to work through them, and nothing about anybody else's van.
"""

from enum import StrEnum

from app.modules.deliveries.constants import DeliveryStatus


class DriverDeliveryStatus(StrEnum):
    PENDING = "pending"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    FAILED = "failed"


#: Slip status -> what the driver's app calls it.
APP_STATUS: dict[str, DriverDeliveryStatus] = {
    DeliveryStatus.SCHEDULED.value: DriverDeliveryStatus.PENDING,
    DeliveryStatus.DISPATCHED.value: DriverDeliveryStatus.PENDING,
    DeliveryStatus.DELIVERED.value: DriverDeliveryStatus.COMPLETED,
    DeliveryStatus.FAILED.value: DriverDeliveryStatus.FAILED,
}

#: The slips a driver may act on. A delivered or failed slip is a receipt, not work.
ACTIONABLE_STATUSES: frozenset[str] = frozenset(
    {DeliveryStatus.SCHEDULED.value, DeliveryStatus.DISPATCHED.value}
)

#: Work queue order on the driver's list: what they have already started comes first, then what
#: is still to do, then what is finished. Same principle as the dispatch board, different
#: audience - a driver mid-trip should not have to scroll past this morning's completed drops.
STATUS_RANK: dict[str, int] = {
    DeliveryStatus.DISPATCHED.value: 0,
    DeliveryStatus.SCHEDULED.value: 1,
    DeliveryStatus.FAILED.value: 2,
    DeliveryStatus.DELIVERED.value: 3,
}

#: How close counts as "at the gate", in metres. Generous on purpose: a handset fix in a built-up
#: area is routinely 50-100 m out, and this number only decides whether the app shows a nudge.
#: **It never blocks a delivery** - a driver standing at a gate their phone cannot locate still
#: has cylinders to hand over.
AT_LOCATION_RADIUS_METRES = 200.0

#: Longest note a driver may attach to a handover.
MAX_NOTE_LENGTH = 500
