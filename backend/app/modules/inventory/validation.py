"""Per-type validation for a recorded movement (spec §11.3).

Which fields a body must carry depends on `type`: a refill needs a quantity, a correction
needs a new count and a reason, a plant return needs to say which bucket it came out of. So
this is a small state machine rather than a list of field constraints, and it runs before the
ledger so nothing is locked or written for a body that was never going to be accepted.

Every failure is the coded `VALIDATION_ERROR` envelope with `detail.fields[].field` naming the
input to fix, and the messages are spec §11.3's own wording - "Enter at least 1", "Required",
"Enter a count of 0 or more", "No change", "Reason required" - because the app shows them
verbatim under the field.

The spec's "Max 94" is deliberately **not** implemented: it was an illustrative figure, and a
refill truck carries more than that. The only upper bound is `MAX_BUCKET_COUNT`, which is about
what the column can hold rather than about how many cylinders a merchant may receive.

The one rule that is about authority rather than shape also lives here: `DISPATCHED` and
`EMPTIES_COLLECTED` are refused outright. They are written by the delivery endpoints against a
real slip, and accepting them from a person would let filled stock leave the godown with no
delivery behind it - the ledger would still add up while describing something that never
happened.
"""

from dataclasses import dataclass

from fastapi import status

from app.modules.inventory.constants import (
    FROM_BUCKETS,
    MAX_BUCKET_COUNT,
    MIN_MOVEMENT_QUANTITY,
    QUANTITY_TYPES,
    SYSTEM_TYPES,
    StockBucket,
    StockMovementType,
)
from app.modules.inventory.schemas import RecordStockMovementRequest
from app.shared.exceptions.api_error import ApiError

SYSTEM_TYPE_MESSAGE = "Dispatch and empties are recorded by the delivery screens, not here."
UNSUPPORTED_TYPE_MESSAGE = "This movement type cannot be recorded here."
NOTE_REQUIRED_MESSAGE = "Reason required"
NO_CHANGE_MESSAGE = "No change"


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


@dataclass(frozen=True)
class CheckedMovement:
    """A body that has passed every rule that does not need the current counts.

    `quantity` is resolved for the three counted types. A correction's quantity cannot be
    known here - it is the distance from the count on the row - so it stays `None` and the
    ledger fills it in under the lock.
    """

    type: StockMovementType
    bucket: StockBucket | None
    quantity: int | None
    new_count: int | None
    note: str | None
    reference_id: str | None


def validate(payload: RecordStockMovementRequest) -> CheckedMovement:
    """Check one movement request, or raise the coded 422."""
    movement_type = payload.type
    _reject_system_type(movement_type)

    if movement_type is StockMovementType.CORRECTION:
        return _correction(payload)
    if movement_type in QUANTITY_TYPES:
        return _counted(payload, movement_type)
    # A type added to the enum but to none of the rules above. Refused rather than guessed at:
    # a movement whose effect on the counts is undefined must not reach the ledger.
    raise invalid("type", "unsupported_movement_type", UNSUPPORTED_TYPE_MESSAGE)


def _reject_system_type(movement_type: StockMovementType) -> None:
    if movement_type in SYSTEM_TYPES:
        raise invalid("type", "system_movement_type", SYSTEM_TYPE_MESSAGE)


def _counted(
    payload: RecordStockMovementRequest, movement_type: StockMovementType
) -> CheckedMovement:
    """RECEIVED_FILLED, SENT_TO_PLANT, MARKED_DAMAGED: a quantity, and sometimes a source."""
    quantity = _quantity(payload.quantity)
    bucket = None
    if movement_type in FROM_BUCKETS:
        bucket = _from_bucket(payload.from_bucket, movement_type)
    return CheckedMovement(
        type=movement_type,
        bucket=bucket,
        quantity=quantity,
        new_count=None,
        note=_clean(payload.note),
        reference_id=_clean(payload.reference_id),
    )


def _correction(payload: RecordStockMovementRequest) -> CheckedMovement:
    """A physical audit overriding the register. Always needs a reason.

    The note is mandatory because a correction is the one movement with no external event
    behind it - no truck, no delivery, no challan. "Physical audit: 3 short vs register" is
    the only thing that will explain the row to whoever reconciles it next month.
    """
    if payload.bucket is None:
        raise invalid("bucket", "bucket_required", "Required")
    note = _clean(payload.note)
    if not note:
        raise invalid("note", "note_required", NOTE_REQUIRED_MESSAGE)
    return CheckedMovement(
        type=StockMovementType.CORRECTION,
        bucket=payload.bucket,
        quantity=None,
        new_count=_new_count(payload.new_count),
        note=note,
        reference_id=_clean(payload.reference_id),
    )


def _quantity(value: int | None) -> int:
    if value is None:
        raise invalid("quantity", "quantity_required", f"Enter at least {MIN_MOVEMENT_QUANTITY}")
    # A request body cannot reach here with a boolean - the schema rejects that before the
    # model is built - but a direct service call can, and `True` would become a quantity of one.
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("quantity", "quantity_not_integer", "Enter a whole number of cylinders")
    if value < MIN_MOVEMENT_QUANTITY:
        raise invalid("quantity", "quantity_too_small", f"Enter at least {MIN_MOVEMENT_QUANTITY}")
    if value > MAX_BUCKET_COUNT:
        # Not a business rule - a storage one. The ledger records whole truckloads, but a
        # six-figure quantity is a keypress that slipped.
        raise invalid("quantity", "quantity_too_large", f"Max {MAX_BUCKET_COUNT:,}")
    return value


def _new_count(value: int | None) -> int:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid("newCount", "new_count_invalid", "Enter a count of 0 or more")
    if value > MAX_BUCKET_COUNT:
        raise invalid("newCount", "new_count_too_large", f"Max {MAX_BUCKET_COUNT}")
    return value


def _from_bucket(value: StockBucket | None, movement_type: StockMovementType) -> StockBucket:
    allowed = FROM_BUCKETS[movement_type]
    if value is None:
        raise invalid("fromBucket", "from_bucket_required", "Required")
    if value not in allowed:
        # Names what is allowed rather than only what was wrong: the app puts this under a
        # bucket selector, and "empty or damaged" tells the user what to pick next.
        options = " or ".join(bucket.value for bucket in allowed)
        raise invalid(
            "fromBucket",
            "from_bucket_not_allowed",
            f"{movement_type.value.replace('_', ' ').title()} can only come from {options}.",
        )
    return value


def _clean(value: str | None) -> str | None:
    """Trim, and treat a whitespace-only string as absent.

    A note of `"   "` from a keyboard that inserted a space must not satisfy "Reason required".
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None
