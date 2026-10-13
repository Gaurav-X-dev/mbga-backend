"""What may be stored as somebody's name.

A customer registered as

    @@@@@@####@@@@@@@@@@@@@@@@@@@@@@@@@@@#₹₹₹₹₹₹₹₹₹__&-+((8889000433456778899((+;;

and the only check in the way was `max_length=160`. By the time it was noticed, that string
had been copied onto the order, the slip, the invoice, the customer's notification and the
stock ledger - a name is not a label on one screen, and cleaning the profile reaches none of
the places it was already written.

The rules have to stay loose, because Indian names are: `M/s R.K. Traders`, `Sharma & Sons`,
`A1 Gas Agency`, `D'Souza`, and names in any script. What is refused is a string that is not
a name in any language.
"""

import pytest

from app.shared.exceptions.api_error import ApiError
from app.shared.validation.names import check_name, looks_like_a_name, tidy

pytestmark = pytest.mark.unit

GARBAGE = "@@@@@@####@@@@@@@@@@@@@@@@@@@@@@@@@@@#₹₹₹₹₹₹₹₹₹__&-+((8889000433456778899((+;;"


# --- Names that must keep working ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "M/s R.K. Traders",
        "Sharma & Sons",
        "A1 Gas Agency",
        "D'Souza",
        "Chandel HERITAGE",
        "गौरव सिंह",  # Devanagari
        "வினோத்",  # Tamil
        "Li",  # two letters is a name
        "Jean-Luc",
        "O'Brien & Co.",
    ],
)
def test_a_real_name_is_accepted(name):
    assert looks_like_a_name(name), name


def test_the_name_is_returned_tidied():
    assert check_name("   Aaryan   foods  ", field="ownerName") == "Aaryan foods"


def test_an_optional_name_may_be_empty():
    assert check_name("", field="ownerName", required=False) == ""


# --- What is refused -----------------------------------------------------------------------------


def test_the_production_case_is_refused():
    """The string that got through, verbatim."""
    assert not looks_like_a_name(GARBAGE)


@pytest.mark.parametrize(
    "value",
    [
        "12345",  # a phone number in the name box
        "...",
        "@@@@",
        "₹₹₹₹₹₹",
        "-----",
        "Ravi@@@@@@@@@@@@@@@@@@@@",  # has a letter, is still not a name
    ],
)
def test_a_string_that_is_not_a_name_is_refused(value):
    assert not looks_like_a_name(tidy(value))


def test_a_refusal_names_the_field_the_form_shows():
    with pytest.raises(ApiError) as caught:
        check_name(GARBAGE, field="ownerName")

    field = caught.value.detail["fields"][0]
    assert field["field"] == "ownerName"
    assert field["code"] == "name_invalid"


def test_the_message_reads_as_an_instruction():
    """It reaches the app as `detail.message` too, so it has to be a sentence."""
    with pytest.raises(ApiError) as caught:
        check_name(GARBAGE, field="ownerName")

    assert caught.value.detail["message"] == "Enter a real name, not symbols or numbers."


def test_a_required_name_may_not_be_blank():
    with pytest.raises(ApiError) as caught:
        check_name("   ", field="ownerName")

    assert caught.value.detail["fields"][0]["code"] == "name_required"


def test_one_character_is_too_short():
    with pytest.raises(ApiError) as caught:
        check_name("R", field="ownerName")

    assert caught.value.detail["fields"][0]["code"] == "name_too_short"


# --- Characters that render as nothing -------------------------------------------------------------


def test_invisible_characters_are_dropped():
    """A name of zero-width joiners passes a length check and shows as blank on every screen."""
    assert tidy("​​​Ravi​") == "Ravi"


def test_a_name_made_only_of_invisible_characters_is_refused():
    with pytest.raises(ApiError) as caught:
        check_name("​​​​", field="ownerName")

    assert caught.value.detail["fields"][0]["code"] == "name_required"


def test_a_newline_does_not_split_the_name_onto_two_lines():
    """It would, on an invoice."""
    assert tidy("Aaryan\nfoods") == "Aaryan foods"
