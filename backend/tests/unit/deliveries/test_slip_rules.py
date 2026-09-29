"""Slip rules that need no database (spec §10).

The state machine, the field checks and the code helpers. Pulled out as unit tests because they
are the parts that decide whether a real-world mistake is catchable: a slip that can be dispatched
twice, a code that a mock value unlocks in production, a status graph with a way back from a
terminal state.
"""

import pytest

from app.modules.deliveries import codes
from app.modules.deliveries.constants import (
    CODE_LENGTH,
    MOCK_CODE,
    STATUS_TRANSITIONS,
    ConfirmationMethod,
    DeliveryStatus,
)
from app.modules.deliveries.validation import (
    check_confirmation_method,
    check_empties,
    check_vehicle_number,
    not_ready_message,
    resolve_driver_name,
    resolve_helper_name,
)
from app.shared.exceptions.api_error import ApiError

pytestmark = [pytest.mark.unit]


class Payload:
    """Enough of `CreateDeliverySlipRequest` for the name resolvers."""

    def __init__(self, driver_name: str | None = None, helper_name: str | None = None) -> None:
        self.driver_name = driver_name
        self.helper_name = helper_name


def failure(callable_, *args) -> tuple[str, str]:
    with pytest.raises(ApiError) as caught:
        callable_(*args)
    field = caught.value.detail["fields"][0]
    return field["field"], field["message"]


# --- The state machine --------------------------------------------------------------------------


def test_a_scheduled_slip_can_only_go_out_or_be_written_off():
    assert STATUS_TRANSITIONS[DeliveryStatus.SCHEDULED.value] == frozenset(
        {DeliveryStatus.DISPATCHED.value, DeliveryStatus.FAILED.value}
    )


def test_a_dispatched_slip_cannot_go_back_to_scheduled():
    """The cylinders have physically gone and the movement is on an append-only ledger.

    Undoing a dispatch is a failed slip and a new one - which is what actually happens when a van
    comes back loaded.
    """
    assert DeliveryStatus.SCHEDULED.value not in STATUS_TRANSITIONS[DeliveryStatus.DISPATCHED.value]


def test_terminal_states_are_dead_ends():
    """A delivered slip is a receipt; a failed one is a record. Neither is editable."""
    assert STATUS_TRANSITIONS[DeliveryStatus.DELIVERED.value] == frozenset()
    assert STATUS_TRANSITIONS[DeliveryStatus.FAILED.value] == frozenset()


def test_every_status_is_in_the_graph():
    """A status with no entry would be silently unmovable rather than explicitly terminal."""
    assert set(STATUS_TRANSITIONS) == {status.value for status in DeliveryStatus}


def test_the_not_ready_message_says_which_step_is_missing():
    """Spec §10.4 asks for "not been dispatched yet" specifically."""
    confirm_first = not_ready_message("DS-0148", "SCHEDULED", DeliveryStatus.DISPATCHED)
    after_failure = not_ready_message("DS-0148", "FAILED", DeliveryStatus.DELIVERED)

    assert confirm_first == "Slip DS-0148 has not been dispatched yet."
    assert "Raise a new slip" in after_failure


# --- Empties ------------------------------------------------------------------------------------


def test_empties_may_be_none_at_all():
    """A first-time customer has nothing to give back."""
    assert check_empties(0, 4) == 0


def test_empties_may_equal_what_was_delivered():
    assert check_empties(4, 4) == 4


def test_more_empties_than_cylinders_is_refused():
    """Otherwise the driver books somebody else's cylinders onto this slip."""
    assert failure(check_empties, 5, 4) == ("emptiesCollected", "Invalid count")


def test_negative_empties_are_refused():
    assert failure(check_empties, -1, 4)[1] == "Invalid count"


def test_a_boolean_is_not_an_empties_count():
    """`True` is an `int` in Python and would otherwise book one empty."""
    assert failure(check_empties, True, 4)[0] == "emptiesCollected"


def test_a_missing_count_is_refused():
    assert failure(check_empties, None, 4)[1] == "Invalid count"


# --- Vehicle ------------------------------------------------------------------------------------


def test_a_vehicle_number_is_upper_cased_and_collapsed():
    """It is read off a plate, so case and stray spacing are noise."""
    assert check_vehicle_number(" mp09  gh 4521 ") == "MP09 GH 4521"


def test_a_vehicle_number_is_required():
    assert failure(check_vehicle_number, "")[0] == "vehicleNumber"
    assert failure(check_vehicle_number, "MP")[0] == "vehicleNumber"


def test_an_odd_but_real_plate_is_accepted():
    """BS, military and older series all differ; refusing a real van at the gate is worse."""
    for plate in ("MP-09-GH-4521", "MP09GH4521", "22 BH 4521 AA"):
        assert check_vehicle_number(plate)


def test_a_plate_with_punctuation_is_refused():
    assert failure(check_vehicle_number, "MP09/GH#4521")[0] == "vehicleNumber"


# --- Crew names ---------------------------------------------------------------------------------


def test_the_account_name_wins_over_a_typed_one():
    """So the slip cannot claim a different name from the phone it notifies."""
    assert resolve_driver_name(Payload(driver_name="Typed Name"), "Arjun Singh") == "Arjun Singh"


def test_a_typed_name_is_accepted_for_a_hired_van():
    assert resolve_driver_name(Payload(driver_name="Hired driver"), None) == "Hired driver"


def test_a_slip_must_name_somebody():
    assert failure(resolve_driver_name, Payload(), None)[0] == "driverName"


def test_a_helper_is_optional():
    assert resolve_helper_name(Payload(), None) is None
    assert resolve_helper_name(Payload(helper_name="  "), None) is None
    assert resolve_helper_name(Payload(helper_name="Ramesh"), None) == "Ramesh"


# --- Confirmation method ------------------------------------------------------------------------


def test_the_two_methods_the_app_can_complete_are_accepted():
    for method in (ConfirmationMethod.OTP, ConfirmationMethod.NONE):
        assert check_confirmation_method(method) is method


@pytest.mark.parametrize("method", [ConfirmationMethod.SIGNATURE, ConfirmationMethod.PHOTO])
def test_a_method_no_screen_can_complete_is_refused(method: ConfirmationMethod):
    """Accepting one would create a slip only a database edit could settle."""
    assert failure(check_confirmation_method, method)[0] == "confirmationMethod"


# --- The code -----------------------------------------------------------------------------------


def test_a_generated_code_is_four_digits():
    for _ in range(50):
        code = codes.generate()
        assert len(code) == CODE_LENGTH
        assert code.isdigit()


def test_codes_are_not_all_the_same():
    """A constant would pass every other test here and be worthless."""
    assert len({codes.generate() for _ in range(40)}) > 1


def test_a_code_verifies_against_its_own_hash():
    code = codes.generate()

    assert codes.matches(code, codes.fingerprint(code), allow_mock=False)


def test_a_wrong_code_does_not_verify():
    assert not codes.matches("0000", codes.fingerprint("1234"), allow_mock=False)


def test_the_mock_code_works_only_where_it_is_allowed():
    """Spec §10.4's "mock accepts 4321", behind the same switch that exposes login OTPs.

    A fixed code that worked in production would let anyone who read the spec confirm any delivery.
    """
    stored = codes.fingerprint("1234")

    assert codes.matches(MOCK_CODE, stored, allow_mock=True)
    assert not codes.matches(MOCK_CODE, stored, allow_mock=False)


def test_the_real_code_still_works_when_the_mock_is_allowed():
    """The switch adds a code, it does not replace the generated one."""
    assert codes.matches("1234", codes.fingerprint("1234"), allow_mock=True)


def test_nothing_verifies_against_a_missing_hash():
    """A slip with no code - method NONE, or already settled - cannot be confirmed by guessing."""
    assert not codes.matches("4321", None, allow_mock=True)
    assert not codes.matches("4321", "", allow_mock=True)


@pytest.mark.parametrize("code", ["", None, "abc", "12345", "123", "12a4", " 123"])
def test_a_malformed_code_is_rejected_before_hashing(code):
    """Checked first, so a typo never costs a verification attempt."""
    assert not codes.is_well_formed(code)


def test_a_four_digit_code_is_well_formed():
    assert codes.is_well_formed("4321")
    assert codes.is_well_formed("0000")
