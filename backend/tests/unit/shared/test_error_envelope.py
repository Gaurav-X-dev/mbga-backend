"""What an app shows when it reads only `detail.message`.

Every app built against this API so far shows the envelope's `message` and ignores `fields`.
That was survivable until the messages people needed were all one level down: a driver who
mistyped a confirmation code read "Some fields are missing or invalid", and so did one who
claimed more empties than the customer was holding - who then reported it as an OTP fault,
because nothing on his screen said otherwise.

Reading `fields[0].message` is still the right thing for an app to do, and the API still says
so. This makes the lazy reading correct too, for the common case where exactly one field is at
fault and its sentence *is* the refusal.
"""

import pytest

from app.shared.exceptions.api_error import error_detail

pytestmark = pytest.mark.unit

GENERIC = "Some fields are missing or invalid."


def field(message: str, *, name: str = "otp", code: str = "incorrect_otp") -> dict:
    return {"field": name, "code": code, "message": message}


def test_one_field_speaks_for_the_whole_refusal():
    """`invalid()` passes no message, so the generic lookup is all there would be."""
    detail = error_detail("VALIDATION_ERROR", None, [field("Incorrect OTP")])

    assert detail["message"] == "Incorrect OTP"


def test_a_written_message_is_never_replaced_by_a_fragment():
    """The case that caught this: a field entry is sometimes a fragment, not a sentence.

    "Not enough filled 19 KG in stock (3 available, 4 needed). Record a refill first." is the
    considered message; "3 available" is meant to sit beside the input. Promoting the fragment
    would be this fix doing the damage it was written to undo.
    """
    written = "Not enough filled 19 KG in stock (3 available, 4 needed). Record a refill first."

    detail = error_detail("INSUFFICIENT_STOCK", written, [field("3 available", name="quantity")])

    assert detail["message"] == written


def test_the_fields_list_is_untouched():
    """Apps that read it properly must see exactly what they saw before."""
    fields = [field("Incorrect OTP")]

    detail = error_detail("VALIDATION_ERROR", None, fields)

    assert detail["fields"] == fields


def test_two_fields_keep_the_generic_summary():
    """No one of them describes the refusal, so neither may speak for it."""
    detail = error_detail(
        "VALIDATION_ERROR",
        None,
        [field("Incorrect OTP"), field("Invalid count", name="emptiesCollected")],
    )

    assert detail["message"] == GENERIC


def test_an_error_with_no_fields_is_unchanged():
    detail = error_detail("ORDER_NOT_CANCELLABLE", "An order that is delivered can no longer be cancelled.")

    assert detail["message"] == "An order that is delivered can no longer be cancelled."
    assert detail["fields"] == []


def test_a_field_with_no_message_does_not_blank_the_summary():
    detail = error_detail("VALIDATION_ERROR", None, [{"field": "otp", "code": "incorrect_otp"}])

    assert detail["message"] == GENERIC


def test_a_whitespace_message_does_not_blank_the_summary():
    detail = error_detail("VALIDATION_ERROR", None, [field("   ")])

    assert detail["message"] == GENERIC


def test_the_code_is_always_the_envelope_s_own():
    """The field's `code` names the field's fault; the envelope's names the kind of refusal."""
    detail = error_detail("VALIDATION_ERROR", None, [field("Incorrect OTP")])

    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["fields"][0]["code"] == "incorrect_otp"
