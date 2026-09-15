import pytest

from app.modules.authentication.mobile_number import normalize_mobile_number

pytestmark = pytest.mark.unit


def test_normalize_indian_mobile_number_with_country_prefix() -> None:
    assert normalize_mobile_number("+91 98765 43210") == "+919876543210"
    assert normalize_mobile_number("9876543210") == "+919876543210"
    assert normalize_mobile_number("91 9876543210") == "+919876543210"


def test_normalize_mobile_rejects_letters() -> None:
    with pytest.raises(ValueError):
        normalize_mobile_number("98765abc210")
