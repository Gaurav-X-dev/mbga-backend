"""A-06, A-15, A-18: code delivery, device/push-token handling and code length."""

import logging

import jwt
import pytest
from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from app.shared.otp.provider import OTPDeliveryError
from tests.integration.authentication.conftest import TEST_OTP, code_of, random_mobile

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

DELIVERY = "/api/v1/delivery/auth"
ADMIN = "/api/v1/admin/auth"
REG = "/api/v1/customer/registration"
DEVICE = {"device_id": "install-1", "device_type": "android", "device_name": "Pixel 8", "app_version": "1.0.0", "fcm_token": "push-token-A"}


@pytest.fixture
def settings_overrides(request) -> dict:
    return getattr(request, "param", {})


async def _session(env, access_token: str) -> LoginSession:
    session_id = jwt.decode(access_token, options={"verify_signature": False})["session_id"]
    return await env.scalar(select(LoginSession).where(LoginSession.id == session_id))


@pytest.mark.parametrize("settings_overrides", [{"dev_fixed_otp_enabled": False, "dev_fixed_otp_code": None}], indirect=True)
async def test_random_code_is_delivered_to_the_provider_only(env):
    driver, _, _ = await env.create_delivery_user()
    response = await env.request_code(DELIVERY, driver.mobile_number)

    delivered = env.provider.sent[-1]
    assert delivered["mobile_number"] == driver.mobile_number
    assert delivered["purpose"] == "DELIVERY_LOGIN"
    assert delivered["expires_in_seconds"] == 300
    code = delivered["otp"]
    assert len(code) == 4 and code.isdigit()
    assert code not in response.text

    challenge = await env.scalar(select(OtpChallenge).where(OtpChallenge.id == response.json()["request_id"]))
    assert (challenge.delivery_status, challenge.delivery_provider, challenge.delivery_reference) == ("SENT", "capture", f"ref-{len(env.provider.sent)}")
    assert code not in challenge.otp_hash

    verify = await env.post(f"{DELIVERY}/otp/verify", json={"request_id": response.json()["request_id"], "otp": code})
    assert verify.status_code == 200


@pytest.mark.parametrize("settings_overrides", [{"dev_fixed_otp_enabled": True}], indirect=True)
async def test_unregistered_number_creates_no_challenge_even_with_the_development_code(env):
    unknown = random_mobile()
    response = await env.request_code(ADMIN, unknown)
    assert (response.status_code, code_of(response)) == (404, "NUMBER_NOT_REGISTERED")
    assert await env.scalar(select(OtpChallenge.id).where(OtpChallenge.mobile_number == unknown)) is None


async def test_delivery_failure_returns_503_and_stores_nothing(env):
    admin = await env.create_user(roles=("super_admin",))
    env.provider.fail_with = OTPDeliveryError("SMS_VENDOR_NOT_INTEGRATED")

    response = await env.request_code(ADMIN, admin.mobile_number)

    assert (response.status_code, code_of(response)) == (503, "OTP_DELIVERY_FAILED")
    assert response.headers["retry-after"] == "30"
    assert await env.scalar(select(OtpChallenge.id).where(OtpChallenge.mobile_number == admin.mobile_number)) is None
    event = await env.scalar(select(AuditLog).where(AuditLog.reason_code == "OTP_DELIVERY_FAILED:SMS_VENDOR_NOT_INTEGRATED"))
    assert event is not None and event.masked_mobile == f"******{admin.mobile_number[-4:]}"


async def test_mock_provider_logs_no_code_or_full_number(env, caplog):
    from app.shared.otp.mock_provider import MockOTPProvider

    # Alembic's logging setup (run by the fixtures) disables loggers created before it.
    logging.getLogger("app.shared.otp.mock_provider").disabled = False
    with caplog.at_level(logging.INFO, logger="app.shared.otp.mock_provider"):
        await MockOTPProvider().send_otp(mobile_number="+919876543210", otp="4826", purpose="ADMIN_LOGIN", expires_in_seconds=300)
    assert "4826" not in caplog.text
    assert "9876543210" not in caplog.text
    assert "******3210" in caplog.text


async def test_device_details_follow_the_session_and_push_token_is_cleared_on_logout(env):
    driver, _, _ = await env.create_delivery_user()
    request = await env.request_code(DELIVERY, driver.mobile_number, device=DEVICE)
    login = (await env.post(f"{DELIVERY}/otp/verify", json={"request_id": request.json()["request_id"], "otp": env.last_code(driver.mobile_number), "device": DEVICE})).json()

    session = await _session(env, login["token"]["access_token"])
    assert (session.device_id, session.device_type, session.device_name, session.app_version, session.push_token) == (
        "install-1",
        "android",
        "Pixel 8",
        "1.0.0",
        "push-token-A",
    )

    kept = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    kept_session = await _session(env, kept.json()["access_token"])
    assert (kept_session.device_id, kept_session.push_token, kept_session.app_version) == ("install-1", "push-token-A", "1.0.0")
    assert (await _session(env, login["token"]["access_token"])).push_token is None

    updated = await env.post(
        f"{DELIVERY}/token/refresh",
        json={"refresh_token": kept.json()["refresh_token"], "device": {"fcm_token": "push-token-B", "app_version": "1.1.0"}},
    )
    updated_session = await _session(env, updated.json()["access_token"])
    assert (updated_session.device_id, updated_session.push_token, updated_session.app_version) == ("install-1", "push-token-B", "1.1.0")

    await env.post(f"{DELIVERY}/logout", json={"refresh_token": updated.json()["refresh_token"]})
    assert (await _session(env, updated.json()["access_token"])).push_token is None


async def test_logout_all_clears_every_push_token(env):
    driver, _, _ = await env.create_delivery_user()
    tokens = []
    for index in range(2):
        device = {**DEVICE, "device_id": f"install-{index}", "fcm_token": f"push-{index}"}
        request = await env.request_code(DELIVERY, driver.mobile_number, device=device)
        verify = await env.post(f"{DELIVERY}/otp/verify", json={"request_id": request.json()["request_id"], "otp": env.last_code(driver.mobile_number), "device": device})
        tokens.append(verify.json()["token"]["access_token"])

    assert (await env.post(f"{DELIVERY}/logout-all", tokens[0])).status_code == 204
    for token in tokens:
        session = await _session(env, token)
        assert session.revoked_reason == "LOGOUT_ALL"
        assert session.push_token is None


@pytest.mark.parametrize("settings_overrides", [{"otp_length": 6}], indirect=True)
async def test_code_length_follows_configuration(env):
    admin = await env.create_user(roles=("super_admin",))
    request_id = (await env.request_code(ADMIN, admin.mobile_number)).json()["request_id"]
    response = await env.post(f"{ADMIN}/otp/verify", json={"request_id": request_id, "otp": "1234"})
    assert (response.status_code, code_of(response)) == (422, "VALIDATION_ERROR")
    assert response.json()["detail"]["fields"][0] == {"field": "otp", "code": "otp_length", "message": "Enter the 6-digit code."}


async def test_codes_with_the_wrong_length_fail_schema_validation(env):
    for otp in ("123", "12345", "12a4", ""):
        response = await env.post(f"{REG}/otp/verify", json={"request_id": "x", "otp": otp})
        assert (response.status_code, code_of(response)) == (422, "VALIDATION_ERROR")


@pytest.mark.parametrize("settings_overrides", [{"dev_expose_otp_in_response": True}], indirect=True)
async def test_dev_otp_is_echoed_only_when_the_development_setting_is_on(env):
    driver, _, _ = await env.create_delivery_user()
    response = await env.request_code(DELIVERY, driver.mobile_number)

    dev_otp = response.json()["dev_otp"]
    assert dev_otp == env.provider.sent[-1]["otp"]
    verify = await env.post(f"{DELIVERY}/otp/verify", json={"request_id": response.json()["request_id"], "otp": dev_otp})
    assert verify.status_code == 200

    resend = await env.post(f"{DELIVERY}/otp/resend", json={"request_id": response.json()["request_id"]})
    if resend.status_code == 202:
        assert resend.json()["dev_otp"] == env.provider.sent[-1]["otp"]


async def test_dev_otp_is_absent_by_default(env):
    driver, _, _ = await env.create_delivery_user()
    response = await env.request_code(DELIVERY, driver.mobile_number)
    assert response.json()["dev_otp"] is None
