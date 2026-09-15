import pytest
from pydantic import ValidationError

from app.config.app import Settings
from app.modules.authentication.schemas import OTPVerifyRequest

pytestmark = pytest.mark.unit


def test_otp_verify_accepts_exactly_four_digit_string() -> None:
    payload = OTPVerifyRequest(request_id="request-id", otp="0123")

    assert payload.otp == "0123"


@pytest.mark.parametrize("otp", ["123", "12345", "12a4", "111111", 1234])
def test_otp_verify_rejects_non_four_digit_string(otp) -> None:
    with pytest.raises(ValidationError):
        OTPVerifyRequest(request_id="request-id", otp=otp)


def test_fixed_otp_rejected_in_production_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_fixed_otp_enabled=True, dev_fixed_otp_code="1234")
