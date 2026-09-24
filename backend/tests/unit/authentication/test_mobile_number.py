import pytest

from app.modules.authentication.mobile_number import (
    InvalidMobileNumberError,
    ensure_india_country_code,
    normalize_mobile_number,
)

pytestmark = pytest.mark.unit


def test_normalize_indian_mobile_number_with_country_prefix() -> None:
    assert normalize_mobile_number("+91 98765 43210") == "+919876543210"
    assert normalize_mobile_number("9876543210") == "+919876543210"
    assert normalize_mobile_number("91 9876543210") == "+919876543210"
    assert normalize_mobile_number("+91-6000000000") == "+916000000000"


def test_normalize_mobile_rejects_letters() -> None:
    with pytest.raises(ValueError):
        normalize_mobile_number("98765abc210")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "98765432",  # too few digits
        "98765432101",  # too many digits
        "+9198765432101",  # too many digits with country code
        "0000000001",  # national number starting with 0
        "+910000000001",
        "5876543210",  # national number starting with 5
        "+449876543210",  # other country code
        "0919876543210",
    ],
)
def test_normalize_mobile_rejects_invalid_indian_numbers(value: str) -> None:
    with pytest.raises(InvalidMobileNumberError):
        normalize_mobile_number(value)


def test_invalid_mobile_error_is_a_value_error_for_existing_handlers() -> None:
    assert issubclass(InvalidMobileNumberError, ValueError)


@pytest.mark.parametrize("code", ["+91", "91", " +91 ", None])
def test_india_country_code_is_accepted(code: str | None) -> None:
    ensure_india_country_code(code)


@pytest.mark.parametrize("code", ["+44", "+1", "", "+911"])
def test_other_country_codes_are_rejected(code: str) -> None:
    with pytest.raises(InvalidMobileNumberError):
        ensure_india_country_code(code)
