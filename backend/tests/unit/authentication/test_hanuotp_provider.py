"""HanuOTP configuration, request construction, response handling and redaction.

Every test here mocks the HTTP transport. Nothing in this file reaches the real vendor: the
provider is billed per message, so a test suite that could send one is a test suite that will
eventually send thousands.
"""

import json
import logging

import httpx
import pytest

from app.config.app import Settings
from app.shared.otp.hanuotp_provider import (
    HanuOTPProvider,
    _sanitize,
    interpret,
    to_national,
)
from app.shared.otp.provider import OTPDeliveryError

pytestmark = pytest.mark.unit

API_KEY = "test-key-not-a-real-one"
BASE_URL = "https://api.hanuotp.in/sms-otp.php"
MOBILE = "+919812345678"
NATIONAL = "9812345678"
OTP = "4821"


def settings(**overrides) -> Settings:
    """A HanuOTP configuration built only from these values.

    `_env_file=None` matters: without it pydantic-settings reads the developer's real `.env`,
    and a test asserting that a missing key is rejected would pass or fail depending on whose
    machine it ran on.
    """
    values = {
        "app_env": "local",
        "sms_provider": "hanuotp",
        "hanuotp_base_url": BASE_URL,
        "hanuotp_api_key": API_KEY,
        "hanuotp_template_id": "default",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def provider_with(handler, **overrides) -> HanuOTPProvider:
    """A provider whose transport is a function, so no socket is ever opened."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HanuOTPProvider(settings(**overrides), client=client)


SUCCESS_BODY = '{"status": "success", "message": "OTP sent"}'
REJECTED_BODY = '{"status": "error", "message": "Invalid API Key"}'


def responder(status: int = 200, text: str = SUCCESS_BODY):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        captured["method"] = request.method
        captured["params"] = dict(request.url.params)
        return httpx.Response(status, text=text)

    return handler, captured


# --- configuration ----------------------------------------------------------------------


def test_a_complete_configuration_is_accepted():
    assert settings().sms_provider == "hanuotp"


@pytest.mark.parametrize(
    ("missing", "name"),
    [("hanuotp_api_key", "HANUOTP_API_KEY"), ("hanuotp_base_url", "HANUOTP_BASE_URL")],
)
def test_selecting_hanuotp_without_its_configuration_fails_at_startup(missing, name):
    """A misconfigured provider must not wait until the first sign-in to reveal itself."""
    with pytest.raises(ValueError, match=name):
        settings(**{missing: None})


def test_a_plain_http_base_url_is_refused():
    """The key and the code travel in the query string, so http would expose both."""
    with pytest.raises(ValueError, match="https"):
        settings(hanuotp_base_url="http://api.hanuotp.in/sms-otp.php")


def test_a_configuration_error_never_echoes_the_key():
    try:
        settings(hanuotp_base_url=None)
    except ValueError as exc:
        assert API_KEY not in str(exc)
    else:
        pytest.fail("an incomplete configuration was accepted")


def test_a_pasted_key_is_trimmed():
    """A key copied with a trailing newline must not become a different key."""
    assert settings(hanuotp_api_key="  the-key\n").hanuotp_api_key == "the-key"


def test_an_unknown_provider_name_is_refused():
    with pytest.raises(ValueError, match="SMS_PROVIDER"):
        Settings(_env_file=None, app_env="local", sms_provider="twilio")


def test_the_mock_provider_stays_the_local_default():
    assert Settings(_env_file=None, app_env="local").sms_provider == "mock"


def test_the_mock_provider_is_refused_outside_local():
    with pytest.raises(ValueError, match="local/development/test"):
        Settings(_env_file=None, app_env="production", jwt_signing_secret="x7Qv2LmZ9pRt4Whd8KcNbJgY3sEuAoI1", sms_provider="mock")


def test_the_live_smoke_switch_is_refused_outside_local():
    with pytest.raises(ValueError, match="local/development/test"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_signing_secret="x7Qv2LmZ9pRt4Whd8KcNbJgY3sEuAoI1",
            sms_provider="hanuotp",
            hanuotp_base_url=BASE_URL,
            hanuotp_api_key=API_KEY,
            hanuotp_live_smoke_test_enabled=True,
        )


def test_the_provider_repr_does_not_carry_the_key():
    """A stray repr in a log line or a traceback must not leak the credential."""
    handler, _ = responder()
    assert API_KEY not in repr(provider_with(handler))


# --- request construction ------------------------------------------------------------------


async def test_the_request_matches_the_vendor_contract():
    handler, captured = responder()
    result = await provider_with(handler).send_otp(
        mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
    )

    assert captured["method"] == "GET"
    assert str(captured["url"]).startswith(BASE_URL)
    assert captured["params"] == {
        "number": NATIONAL,
        "OTP": OTP,
        "apikey": API_KEY,
        "templatesid": "default",
    }
    assert result.provider == "hanuotp"


async def test_the_template_id_comes_from_configuration():
    handler, captured = responder()
    await provider_with(handler, hanuotp_template_id="mbga-login").send_otp(
        mobile_number=MOBILE, otp=OTP, purpose="MERCHANT_LOGIN", expires_in_seconds=300
    )
    assert captured["params"]["templatesid"] == "mbga-login"


async def test_the_backends_own_code_is_sent_unchanged():
    """The vendor is a courier. It never generates a code, and the code is not transformed."""
    handler, captured = responder()
    await provider_with(handler).send_otp(
        mobile_number=MOBILE, otp="0007", purpose="ADMIN_LOGIN", expires_in_seconds=300
    )
    assert captured["params"]["OTP"] == "0007"


@pytest.mark.parametrize("stored", ["+919812345678", "9812345678"])
async def test_the_stored_number_is_reduced_to_the_national_form(stored):
    handler, captured = responder()
    await provider_with(handler).send_otp(
        mobile_number=stored, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
    )
    assert captured["params"]["number"] == NATIONAL


@pytest.mark.parametrize("bad", ["+15551234567", "98123456", "+911234567890", "abcdefghij", ""])
def test_a_number_the_vendor_cannot_use_is_refused_before_the_request(bad):
    """A malformed number must not reach a paid endpoint."""
    with pytest.raises(OTPDeliveryError, match="HANUOTP_UNSUPPORTED_NUMBER"):
        to_national(bad)


async def test_query_parameters_are_encoded_rather_than_concatenated():
    """A key containing URL-significant characters must not break out of its parameter."""
    handler, captured = responder()
    await provider_with(handler, hanuotp_api_key="a&b=c d").send_otp(
        mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
    )
    assert captured["params"]["apikey"] == "a&b=c d"
    assert captured["params"]["templatesid"] == "default"


# --- response handling -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        '{"status": "success", "message": "OTP sent"}',
        '{"status": "SUCCESS", "message": "queued"}',
        '{"status": "success", "messageId": "abc-123"}',
        # Not the literal word "success". The failure shape is what was verified live, so a
        # non-failure status counts as delivered - otherwise an unexpected success wording
        # would return 503 for a message the customer actually received.
        '{"status": "sent"}',
        '{"status": "ok", "messageId": "MSG-778812"}',
    ],
)
async def test_anything_that_is_not_an_explicit_failure_is_delivered(body):
    """Verified against the live endpoint: `status` is the verdict, not the HTTP code."""
    handler, _ = responder(200, body)
    result = await provider_with(handler).send_otp(
        mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
    )
    assert result.provider == "hanuotp"


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Invalid API Key", "HANUOTP_INVALID_API_KEY"),
        ("Missing required parameters (number, OTP, apikey, templatesid)", "HANUOTP_BAD_REQUEST"),
        ("Invalid mobile number. Only 10-digit Indian numbers starting with 6,7,8,9 are supported.", "HANUOTP_UNSUPPORTED_NUMBER"),
        ("Insufficient balance", "HANUOTP_INSUFFICIENT_BALANCE"),
        ("Template not approved", "HANUOTP_TEMPLATE_REJECTED"),
        ("Something else entirely", "HANUOTP_REJECTED"),
    ],
)
async def test_the_vendors_own_error_messages_map_to_stable_codes(message, reason):
    """Every one of these was observed live. The vendor answers 200 even when it refuses."""
    handler, _ = responder(200, json.dumps({"status": "error", "message": message}))
    with pytest.raises(OTPDeliveryError, match=reason):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


async def test_the_vendors_message_text_never_becomes_the_reason():
    """Reasons reach the audit log, so they are our own short codes, not free-form vendor text."""
    handler, _ = responder(200, json.dumps({"status": "error", "message": f"key {API_KEY} rejected for {NATIONAL}"}))
    with pytest.raises(OTPDeliveryError) as raised:
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )
    assert raised.value.reason == "HANUOTP_REJECTED"
    assert API_KEY not in raised.value.reason
    assert NATIONAL not in raised.value.reason


async def test_an_empty_body_is_not_assumed_to_be_success():
    handler, _ = responder(200, "")
    with pytest.raises(OTPDeliveryError, match="HANUOTP_EMPTY_RESPONSE"):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


@pytest.mark.parametrize("body", ["not json at all", '{"unexpected": "shape"}', "[1, 2, 3]"])
async def test_a_body_without_a_status_verdict_is_refused_rather_than_guessed(body):
    """Reporting a success we cannot see leaves the user waiting for an SMS forever."""
    handler, _ = responder(200, body)
    with pytest.raises(OTPDeliveryError, match="HANUOTP_UNRECOGNISED_RESPONSE"):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


@pytest.mark.parametrize(("status", "retryable"), [(400, False), (401, False), (404, False), (500, True), (503, True)])
def test_http_errors_map_to_reasons_with_the_right_retryability(status, retryable):
    with pytest.raises(OTPDeliveryError) as raised:
        interpret(status, "whatever the body says")
    assert raised.value.reason == f"HANUOTP_HTTP_{status}"
    assert raised.value.retryable is retryable


async def test_a_timeout_is_reported_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(OTPDeliveryError, match="HANUOTP_TIMEOUT"):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


async def test_a_connection_failure_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(OTPDeliveryError, match="HANUOTP_UNREACHABLE"):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


async def test_the_default_configuration_makes_exactly_one_request():
    """Retries are zero by default: a second attempt is a second charge."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(OTPDeliveryError):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )
    assert len(calls) == 1


async def test_retries_are_bounded_when_deliberately_enabled():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(OTPDeliveryError):
        await provider_with(handler, hanuotp_max_retries=2).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )
    assert len(calls) == 3


async def test_a_declared_failure_is_never_retried():
    """A rejected message would be rejected again; retrying only spends money."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=REJECTED_BODY)

    with pytest.raises(OTPDeliveryError):
        await provider_with(handler, hanuotp_max_retries=3).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )
    assert len(calls) == 1



async def test_an_html_body_is_reported_as_an_edge_block_not_a_rejection():
    """A CDN or bot-protection page is not the vendor answering.

    Observed live: the endpoint sits behind a "Checking your browser" challenge that returns
    HTML to any server-side client. Calling that HANUOTP_REJECTED would send the operator
    hunting for a bad API key when the request never reached the API.
    """
    handler, _ = responder(200, "<!DOCTYPE html><html><title>Just a moment...</title></html>")
    with pytest.raises(OTPDeliveryError, match="HANUOTP_BLOCKED_BY_EDGE"):
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )


async def test_the_request_identifies_this_client():
    """An unnamed client is harder for the vendor's support to trace."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, text=SUCCESS_BODY)

    await provider_with(handler).send_otp(
        mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
    )
    assert "MBGA-Backend" in captured["ua"]


# --- redaction ----------------------------------------------------------------------------------


def sanitized(text: str) -> str:
    response = httpx.Response(200, text=text)
    return _sanitize(response, national=NATIONAL, otp=OTP, api_key=API_KEY)


@pytest.mark.parametrize(
    "echoed",
    [
        f"sent to {NATIONAL}",
        f"OTP {OTP} delivered",
        f"apikey={API_KEY} accepted",
        f"Your MBGA code is {OTP}. Sent to {NATIONAL} using {API_KEY}.",
    ],
)
def test_a_vendor_body_that_echoes_a_secret_is_redacted(echoed):
    cleaned = sanitized(echoed)
    assert API_KEY not in cleaned
    assert NATIONAL not in cleaned
    assert OTP not in cleaned


def test_any_remaining_long_digit_run_is_redacted():
    """Catches a code or a number the vendor reformatted before echoing it."""
    assert "98123" not in sanitized("delivered to 98123 45678")


def test_a_chatty_body_cannot_fill_the_reference_column():
    assert len(sanitized("sent " + "x" * 5000)) <= 200


def test_an_undecodable_body_does_not_crash_the_send():
    response = httpx.Response(200, content=b"\xff\xfe\x00bad bytes")
    assert isinstance(_sanitize(response, national=NATIONAL, otp=OTP, api_key=API_KEY), str)


async def test_logs_carry_a_masked_number_and_nothing_else():
    """Capture the provider's own logger directly.

    `caplog` attaches to the root logger, so it sees nothing once another part of the suite
    turns off propagation on an ancestor — which made this test pass or fail depending on
    which other tests ran first. Attaching here removes that dependency entirely.
    """
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    provider_logger = logging.getLogger("app.shared.otp.hanuotp_provider")
    collector = Collector()
    provider_logger.addHandler(collector)
    previous_level = provider_logger.level
    provider_logger.setLevel(logging.WARNING)
    try:
        handler, _ = responder(200, REJECTED_BODY)
        with pytest.raises(OTPDeliveryError):
            await provider_with(handler).send_otp(
                mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
            )
    finally:
        provider_logger.removeHandler(collector)
        provider_logger.setLevel(previous_level)

    logged = "\n".join(record.getMessage() for record in records)
    assert "******5678" in logged
    assert API_KEY not in logged
    assert OTP not in logged
    assert NATIONAL not in logged
    # The URL carries both the key and the code, so it must never appear.
    assert "sms-otp.php" not in logged
    assert "apikey" not in logged


async def test_an_exception_message_carries_no_secret():
    handler, _ = responder(200, json.dumps({"status": "error", "message": f"key {API_KEY} for {NATIONAL}"}))
    with pytest.raises(OTPDeliveryError) as raised:
        await provider_with(handler).send_otp(
            mobile_number=MOBILE, otp=OTP, purpose="CUSTOMER_LOGIN", expires_in_seconds=300
        )
    message = str(raised.value)
    assert API_KEY not in message
    assert NATIONAL not in message
    assert OTP not in message


def test_the_stored_reference_is_a_sanitized_value():
    """Whatever ends up in `delivery_reference` has already been through redaction."""
    body = json.dumps({"status": "success", "messageId": f"ref-{API_KEY}"})
    reference = interpret(200, sanitized(body))
    assert reference is not None
    assert API_KEY not in reference
