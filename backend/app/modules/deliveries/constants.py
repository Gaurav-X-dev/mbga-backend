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
        {DeliveryStatus.DELIVERED.value, DeliveryStatus.FAILED.value}
    ),
    DeliveryStatus.DELIVERED.value: frozenset(),
    DeliveryStatus.FAILED.value: frozenset(),
}

#: List ordering, spec §10.1: "DISPATCHED -> SCHEDULED -> FAILED -> DELIVERED, then newest
#: scheduledDate". It is a work queue, not a log: what is on the road comes first, then what
#: has to go out, then what went wrong. Delivered slips are last because they need nobody.
STATUS_RANK: dict[str, int] = {
    DeliveryStatus.DISPATCHED.value: 0,
    DeliveryStatus.SCHEDULED.value: 1,
    DeliveryStatus.FAILED.value: 2,
    DeliveryStatus.DELIVERED.value: 3,
}

#: `status = ALL` on the list filter (spec §10.1).
ALL_STATUSES = "ALL"

#: Order statuses a slip may be raised against. A slip is the instruction to load a van, so the
#: order has to be one the merchant has already accepted - not one still `PLACED` and unreviewed,
#: and certainly not one already cancelled or out.
#:
#: `CONFIRMED` alone, now that `PREPARING` is gone: raising a slip no longer moves the order at
#: all. It sits confirmed until the van is actually dispatched, which is the first moment anything
#: has physically happened.
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
