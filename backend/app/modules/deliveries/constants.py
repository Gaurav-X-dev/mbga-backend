"""Delivery vocabulary: slip statuses, how they are ordered, and the proof-of-delivery code.

A **delivery slip** is the piece of paper the van runs on. It is created against a confirmed
order with a vehicle, a driver and a date; it leaves the godown (`DISPATCHED`); and it comes
back either confirmed by the customer (`DELIVERED`) or not (`FAILED`).

The statuses are one-way. A slip that has left cannot go back to `SCHEDULED`, because the
cylinders have physically gone and the stock movement that recorded it is on an append-only
ledger. Undoing a dispatch is a `FAILED` slip and a new one - which is also what actually
happens in a godown when a van comes back loaded.
"""

from enum import StrEnum


class DeliveryStatus(StrEnum):
    """Spec §2 `DeliveryStatus`."""

    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ON_LOCATION = "ON_LOCATION"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class ConfirmationMethod(StrEnum):
    """Spec §2 `ConfirmationMethod`. Phase 1 UI supports `OTP` and `NONE`."""

    OTP = "OTP"
    SIGNATURE = "SIGNATURE"
    PHOTO = "PHOTO"
    NONE = "NONE"


#: What the app may ask for in Phase 1 (spec §2). Signature and photo capture are not built,
#: so accepting them here would create slips that cannot be confirmed by any screen.
SUPPORTED_CONFIRMATION_METHODS: frozenset[ConfirmationMethod] = frozenset(
    {ConfirmationMethod.OTP, ConfirmationMethod.NONE}
)

#: Allowed moves. Terminal states are dead ends on purpose: a delivered slip is a receipt.
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    DeliveryStatus.SCHEDULED.value: frozenset(
        {DeliveryStatus.DISPATCHED.value, DeliveryStatus.FAILED.value}
    ),
    DeliveryStatus.DISPATCHED.value: frozenset(
        {
            DeliveryStatus.ON_LOCATION.value,
            DeliveryStatus.DELIVERED.value,
            DeliveryStatus.FAILED.value,
        }
    ),
    DeliveryStatus.ON_LOCATION.value: frozenset(
        {DeliveryStatus.DELIVERED.value, DeliveryStatus.FAILED.value}
    ),
    DeliveryStatus.DELIVERED.value: frozenset(),
    DeliveryStatus.FAILED.value: frozenset(),
}

#: What each status is called on a screen. Without this the apps prettify the raw enum
#: themselves, and they do not agree: the deliveries list showed "Dispatched" next to a bare
#: "ON_LOCATION", because title-casing one word works and title-casing two with an underscore
#: does not. The wording lives here so all four apps read the same sentence.
STATUS_LABELS: dict[str, str] = {
    DeliveryStatus.SCHEDULED.value: "Scheduled",
    DeliveryStatus.DISPATCHED.value: "Out for Delivery",
    DeliveryStatus.ON_LOCATION.value: "At Customer",
    DeliveryStatus.DELIVERED.value: "Delivered",
    DeliveryStatus.FAILED.value: "Cancelled",
}


def status_label(code: str) -> str:
    """What a slip status is called. Falls back to a readable form of an unknown code."""
    return STATUS_LABELS.get(code, code.replace("_", " ").title())


#: List ordering, spec §10.1: "DISPATCHED -> SCHEDULED -> FAILED -> DELIVERED, then newest
#: scheduledDate". It is a work queue, not a log: what is on the road comes first, then what
#: has to go out, then what went wrong. Delivered slips are last because they need nobody.
STATUS_RANK: dict[str, int] = {
    DeliveryStatus.ON_LOCATION.value: 0,
    DeliveryStatus.DISPATCHED.value: 1,
    DeliveryStatus.SCHEDULED.value: 2,
    DeliveryStatus.FAILED.value: 3,
    DeliveryStatus.DELIVERED.value: 4,
}

# Slips that still occupy a vehicle/crew, and the subset whose cylinders are already on the van.
LIVE_STATUSES: frozenset[str] = frozenset(
    {
        DeliveryStatus.SCHEDULED.value,
        DeliveryStatus.DISPATCHED.value,
        DeliveryStatus.ON_LOCATION.value,
    }
)
IN_TRANSIT_STATUSES: frozenset[str] = frozenset(
    {DeliveryStatus.DISPATCHED.value, DeliveryStatus.ON_LOCATION.value}
)

#: `status = ALL` on the list filter (spec §10.1).
ALL_STATUSES = "ALL"

#: Order statuses a slip may be raised against. A slip is the instruction to load a van, so the
#: order has to be one the merchant has already accepted - not one still `PLACED` and unreviewed,
#: and certainly not one already cancelled or out.
#:
#: `CONFIRMED` alone, now that `PREPARING` is gone: raising a slip no longer moves the order at
#: all. It sits confirmed until the van is actually dispatched, which is the first moment anything
#: has physically happened.
#: `OUT_FOR_DELIVERY` is here too, and only because a van can come back loaded. Failing a slip
#: deliberately leaves the order out - it really did go out, and walking it backwards would lose
#: that - so without this the office could never raise the replacement slip that `fail()`'s own
#: docstring tells them to, and the order would sit undeliverable for ever. It is safe because the
#: caller refuses first when any slip is still live, so reaching this check means nothing is
#: carrying the order.
SLIPPABLE_ORDER_STATUSES: frozenset[str] = frozenset({"CONFIRMED"})

# --- The proof-of-delivery code --------------------------------------------------------------
#
# Four digits the customer reads out to the driver at the gate (spec §10.4). It is deliberately
# *not* run through the login OTP tables: those carry per-IP and per-number throttles sized for
# sign-in abuse, and a driver standing at a gate retrying a code the customer misread must not
# be able to lock that customer out of their own app. So the code lives on the slip, hashed
# with the same helper the login codes use, with its own small attempt budget.

#: Digits in the code. Four, as the spec fixes; it is read out loud, not typed from a password
#: manager.
CODE_LENGTH = 4

#: How many wrong codes before the slip has to be confirmed another way. Generous, because a
#: misheard digit at a noisy gate is the common case and a locked slip means a wasted trip.
MAX_CODE_ATTEMPTS = 10

#: The fixed code the spec's mock accepts. Honoured **only** where the deployment already
#: exposes OTPs in responses (`dev_expose_otp_in_response`), which is local and staging - the
#: same switch the login OTP uses. In production the real generated code is the only one.
MOCK_CODE = "4321"

#: Longest note a driver or the office may attach on confirmation or failure.
MAX_NOTE_LENGTH = 500


class CancellationReason(StrEnum):
    """Why a run did not deliver, as the driver picks it from a list.

    In code rather than in the `constants` table because the backend validates against it and
    because `OTHER` carries a rule - it is the one that demands the driver write something. A
    row an operator could add would be a choice the cancel endpoint then refused. The **labels**
    are seeded into `constants` and may be reworded freely; only the codes are fixed.
    """

    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    CUSTOMER_REFUSED = "CUSTOMER_REFUSED"
    PAYMENT_ISSUE = "PAYMENT_ISSUE"
    ADDRESS_UNREACHABLE = "ADDRESS_UNREACHABLE"
    OTHER = "OTHER"
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"


#: What the driver app shows, in this order. The labels are the default wording; an operator may
#: change them in `constants` without a release.
CANCELLATION_REASON_LABELS: dict[CancellationReason, str] = {
    CancellationReason.CUSTOMER_UNAVAILABLE: "Customer Unavailable / Shop Closed",
    CancellationReason.CUSTOMER_REFUSED: "Customer Refused Delivery",
    CancellationReason.PAYMENT_ISSUE: "Payment Issue / Dispute",
    CancellationReason.ADDRESS_UNREACHABLE: "Address Unreachable / Wrong Location",
    CancellationReason.VEHICLE_BREAKDOWN: "Vehicle Breakdown / Road Blocked",
    CancellationReason.OTHER: "Other Reason",
}

#: Reasons that say nothing on their own. "Other" with no note is a cancelled delivery nobody
#: can account for afterwards, which is the one thing the reason exists to prevent.
REASONS_REQUIRING_NOTES: frozenset[CancellationReason] = frozenset({CancellationReason.OTHER})
