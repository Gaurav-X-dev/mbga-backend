"""Per-type validation of a recorded movement (spec §11.3).

The spec's error strings are asserted verbatim. They are shown under the field on the Record
Stock Movement sheet, so a reworded message is a visible change to the app - which is exactly
the kind of thing that should fail a test rather than ship quietly.
"""

import pytest

from app.modules.inventory.constants import (
    MAX_BUCKET_COUNT,
    StockBucket,
    StockMovementType,
)
from app.modules.inventory.schemas import RecordStockMovementRequest
from app.modules.inventory.validation import validate
from app.shared.exceptions.api_error import ApiError

pytestmark = [pytest.mark.unit]


def body(**overrides) -> RecordStockMovementRequest:
    return RecordStockMovementRequest.model_validate(
        {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 60, **overrides}
    )


def failure(**overrides) -> tuple[str, str, str]:
    """Validate and return (code, field, message) of the refusal."""
    with pytest.raises(ApiError) as caught:
        validate(body(**overrides))
    detail = caught.value.detail
    field = detail["fields"][0]
    return detail["code"], field["field"], field["message"]


# --- The types a person may post -------------------------------------------------------------


def test_a_refill_needs_only_a_quantity():
    checked = validate(body(type="RECEIVED_FILLED", quantity=60))

    assert checked.type is StockMovementType.RECEIVED_FILLED
    assert checked.quantity == 60
    assert checked.bucket is None


def test_a_plant_return_must_say_which_bucket_it_came_from():
    code, field, message = failure(type="SENT_TO_PLANT", fromBucket=None)

    assert (code, field, message) == ("VALIDATION_ERROR", "fromBucket", "Required")


def test_a_plant_return_cannot_send_filled_cylinders_back():
    """Sending a full cylinder to BPCL is a dispatch, not a plant return."""
    _code, field, message = failure(type="SENT_TO_PLANT", fromBucket="filled")

    assert field == "fromBucket"
    assert "empty or damaged" in message


def test_a_plant_return_accepts_empties_and_write_offs():
    for bucket in ("empty", "damaged"):
        checked = validate(body(type="SENT_TO_PLANT", fromBucket=bucket, quantity=12))
        assert checked.bucket is StockBucket(bucket)


def test_marking_damaged_can_condemn_a_filled_or_an_empty_cylinder():
    for bucket in ("filled", "empty"):
        assert validate(body(type="MARKED_DAMAGED", fromBucket=bucket, quantity=2)).bucket


def test_marking_damaged_cannot_come_from_the_damaged_bucket():
    """It is already there; the movement would be a no-op that reads as a loss."""
    _code, field, _message = failure(type="MARKED_DAMAGED", fromBucket="damaged")

    assert field == "fromBucket"


# --- Quantity -------------------------------------------------------------------------------


def test_quantity_must_be_present():
    _code, field, message = failure(quantity=None)

    assert (field, message) == ("quantity", "Enter at least 1")


def test_quantity_must_be_at_least_one():
    """Zero is not a movement. The spec's wording, verbatim."""
    assert failure(quantity=0)[2] == "Enter at least 1"


def test_a_negative_quantity_is_refused_rather_than_flipped():
    """Direction comes from `type`, never from the sign of the quantity."""
    assert failure(quantity=-5)[2] == "Enter at least 1"


def test_a_whole_truckload_is_accepted():
    """No business cap on a movement.

    A refill truck of 5 KG cylinders carries several hundred, and forcing a godown to split one
    challan across four movements would leave the ledger unable to match the paperwork.
    """
    for quantity in (94, 95, 300, 1_200):
        assert validate(body(quantity=quantity)).quantity == quantity


def test_only_a_storage_ceiling_remains():
    """Six figures is a keypress that slipped, not a delivery."""
    assert validate(body(quantity=MAX_BUCKET_COUNT)).quantity == MAX_BUCKET_COUNT
    _code, field, _message = failure(quantity=MAX_BUCKET_COUNT + 1)
    assert field == "quantity"


def test_a_boolean_is_not_a_quantity():
    """`True` is an `int` in Python and would otherwise book one cylinder."""
    _code, field, _message = failure(quantity=True)

    assert field == "quantity"


# --- Corrections ----------------------------------------------------------------------------


def correction(**overrides) -> dict:
    return {
        "type": "CORRECTION",
        "cylinderType": "LPG_5KG",
        "bucket": "filled",
        "newCount": 237,
        "note": "Physical audit: 3 short vs register",
        "quantity": None,
        **overrides,
    }


def test_a_correction_carries_a_new_count_and_no_quantity():
    checked = validate(body(**correction()))

    assert checked.type is StockMovementType.CORRECTION
    assert checked.new_count == 237
    # Resolved in the ledger, under the row lock: it is the distance from the current count.
    assert checked.quantity is None


def test_a_correction_must_name_the_bucket_it_is_correcting():
    _code, field, message = failure(**correction(bucket=None))

    assert (field, message) == ("bucket", "Required")


def test_a_correction_always_needs_a_reason():
    """The one movement with no truck, challan or delivery behind it."""
    _code, field, message = failure(**correction(note=None))

    assert (field, message) == ("note", "Reason required")


def test_a_whitespace_reason_is_not_a_reason():
    assert failure(**correction(note="   "))[2] == "Reason required"


def test_a_new_count_of_zero_is_legitimate():
    """A godown really can be empty of one type, and an audit has to be able to say so."""
    assert validate(body(**correction(newCount=0))).new_count == 0


def test_a_negative_new_count_is_refused():
    _code, field, message = failure(**correction(newCount=-1))

    assert (field, message) == ("newCount", "Enter a count of 0 or more")


def test_a_missing_new_count_is_refused():
    assert failure(**correction(newCount=None))[2] == "Enter a count of 0 or more"


def test_an_absurd_new_count_is_refused():
    """An unbounded count is how a slipped keypress becomes a stock level nobody can explain."""
    _code, field, _message = failure(**correction(newCount=10_000_000))

    assert field == "newCount"


# --- What the app may not post ---------------------------------------------------------------


@pytest.mark.parametrize("movement_type", ["DISPATCHED", "EMPTIES_COLLECTED"])
def test_system_movements_are_refused(movement_type: str):
    """Spec §11.3: these are written by the delivery endpoints.

    Accepting one here would let filled stock leave the godown with no delivery behind it -
    the ledger would still add up while describing something that never happened.
    """
    code, field, message = failure(type=movement_type)

    assert (code, field) == ("VALIDATION_ERROR", "type")
    assert "delivery screens" in message


# --- Trimming --------------------------------------------------------------------------------


def test_a_reference_is_trimmed_and_an_empty_one_is_dropped():
    """A challan number pasted with a trailing newline must not reach the ledger with it."""
    assert validate(body(referenceId="  BPCL/CH/22871 ")).reference_id == "BPCL/CH/22871"
    assert validate(body(referenceId="   ")).reference_id is None
