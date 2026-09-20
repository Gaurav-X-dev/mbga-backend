"""A-06: SMS provider contract, retries, timeouts and configuration guards."""

import asyncio
import secrets

import pytest
from pydantic import ValidationError

from app.config.app import Settings
from app.modules.authentication.dependencies import get_otp_provider
from app.shared.otp.mock_provider import MockOTPProvider
from app.shared.otp.provider import OTPDeliveryError
from app.shared.otp.sms_provider import SMSOTPProvider

pytestmark = pytest.mark.unit

SEND = {"mobile_number": "+919876543210", "otp": "4826", "purpose": "ADMIN_LOGIN", "expires_in_seconds": 300}


def _sms_settings(**overrides) -> Settings:
    values = {
        "app_env": "staging",
        "jwt_signing_secret": secrets.token_urlsafe(48),
        "sms_provider": "sms",
        "sms_api_base_url": "https://sms.example.invalid/api",
        "sms_api_key": "test-key",
        "sms_sender_id": "MBGA",
        "sms_timeout_seconds": 0.05,
        "sms_max_retries": 2,
        **overrides,
    }
    return Settings(_env_file=None, **values)


class ScriptedProvider(SMSOTPProvider):
    def __init__(self, settings: Settings, outcomes: list) -> None:
        super().__init__(settings)
        self.outcomes = outcomes
        self.calls = 0

    async def _dispatch(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if outcome == "slow":
            await asyncio.sleep(1)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_mock_provider_is_rejected_outside_local() -> None:
    with pytest.raises(ValidationError):
        _sms_settings(sms_provider="mock")


def test_unknown_provider_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sms_provider="twilio-ish")


def test_provider_selection() -> None:
    assert isinstance(get_otp_provider(Settings(_env_file=None)), MockOTPProvider)
    assert isinstance(get_otp_provider(_sms_settings()), SMSOTPProvider)


def test_sms_provider_requires_its_settings() -> None:
    with pytest.raises(RuntimeError, match="SMS_API_KEY"):
        SMSOTPProvider(_sms_settings(sms_api_key=None))


def test_fixed_code_must_match_the_code_length() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, otp_length=4, dev_fixed_otp_enabled=True, dev_fixed_otp_code="123456")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, otp_length=4, dev_fixed_otp_enabled=True, dev_fixed_otp_code="CHANGE_ME")
    assert Settings(_env_file=None, otp_length=4, dev_fixed_otp_enabled=True, dev_fixed_otp_code="4826").dev_fixed_otp_code == "4826"


async def test_unintegrated_vendor_fails_without_retrying() -> None:
    provider = SMSOTPProvider(_sms_settings())
    with pytest.raises(OTPDeliveryError) as error:
        await provider.send_otp(**SEND)
    assert error.value.reason == "SMS_VENDOR_NOT_INTEGRATED"
    assert "4826" not in str(error.value)


async def test_retryable_failures_and_timeouts_are_retried() -> None:
    provider = ScriptedProvider(_sms_settings(), [OTPDeliveryError("SMS_503", retryable=True), "slow", "msg-123"])
    result = await provider.send_otp(**SEND)
    assert (result.provider, result.reference, provider.calls) == ("sms", "msg-123", 3)


async def test_retries_stop_at_the_configured_limit() -> None:
    provider = ScriptedProvider(_sms_settings(sms_max_retries=1), [OTPDeliveryError("SMS_503", retryable=True)] * 3)
    with pytest.raises(OTPDeliveryError):
        await provider.send_otp(**SEND)
    assert provider.calls == 2


async def test_permanent_failures_are_not_retried(caplog) -> None:
    provider = ScriptedProvider(_sms_settings(), [OTPDeliveryError("SMS_INVALID_NUMBER")])
    with pytest.raises(OTPDeliveryError):
        await provider.send_otp(**SEND)
    assert provider.calls == 1
    assert "4826" not in caplog.text and "9876543210" not in caplog.text
