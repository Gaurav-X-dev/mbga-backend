"""A-08, A-11: mobile response contracts, OTP rules and the error envelope, per app."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select, update

from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.users.models import User
from tests.integration.authentication.conftest import TEST_OTP, code_of, random_mobile

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ADMIN = "/api/v1/admin/auth"
MERCHANT = "/api/v1/merchant/auth"
DELIVERY = "/api/v1/delivery/auth"
CUSTOMER = "/api/v1/customer/auth"
REG = "/api/v1/customer/registration"
ACCOUNT_KEYS = {
    "user_id",
    "login_channel",
    "user_type",
    "session_type",
    "role",
    "active_roles",
    "account_status",
    "approval_status",
    "profile_completion_status",
    "next_action",
    "merchant",
    "delivery_profile",
    "customer_profile",
}
SECRET_WORDS = ("password", "otp_hash", "refresh_token_hash", "secret", "Traceback")


def _assert_error_envelope(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    detail = response.json()["detail"]
    assert set(detail) == {"code", "message", "fields", "request_id"}
    assert detail["code"] == code
    assert detail["message"] and "_" not in detail["message"]
    assert detail["request_id"] == response.headers["x-request-id"]
    assert all(word not in response.text for word in SECRET_WORDS)


async def test_delivery_verify_and_me_contract(env):
    driver, merchant, profile = await env.create_delivery_user()
    login = await env.sign_in(DELIVERY, driver.mobile_number)

    assert ACCOUNT_KEYS | {"token", "is_new_user", "code", "message"} == set(login)
    assert login["user_type"] == "DELIVERY_PARTNER"
    assert login["role"] == "driver"
    assert login["active_roles"] == ["driver"]
    assert login["next_action"] == "OPEN_DELIVERY_HOME"
    assert login["merchant"]["code"] == merchant.code
    assert login["delivery_profile"] == {
        "id": profile.id,
        "delivery_user_type": "DRIVER",
        "employee_code": profile.employee_code,
        "status": "ACTIVE",
        "approval_status": "APPROVED",
    }
    assert login["customer_profile"] is None
    assert set(login["token"]) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert login["token"]["token_type"] == "Bearer"
    assert login["token"]["expires_in"] == 900

    me = (await env.get(f"{DELIVERY}/me", login["token"]["access_token"])).json()
    assert ACCOUNT_KEYS <= set(me)
    assert me["delivery_profile"]["id"] == profile.id
    assert me["profile"]["id"] == profile.id
    assert me["status"] == me["account_status"] == "ACTIVE"


async def test_duplicate_role_codes_are_not_repeated(env):
    driver, merchant, _ = await env.create_delivery_user()
    await env.assign_role(driver.id, "driver", scope=("merchant", merchant.id))
    login = await env.sign_in(DELIVERY, driver.mobile_number)
    assert login["active_roles"] == ["driver"]


async def test_merchant_and_admin_contracts(env):
    manager, merchant = await env.create_merchant_staff(roles=("accountant", "manager"))
    merchant_login = await env.sign_in(MERCHANT, manager.mobile_number)
    assert merchant_login["user_type"] == "MERCHANT_STAFF"
    assert merchant_login["role"] == "manager"
    assert merchant_login["active_roles"] == ["manager", "accountant"]
    assert merchant_login["next_action"] == "OPEN_MERCHANT_HOME"
    assert merchant_login["merchant"] == {
        "id": merchant.id,
        "code": merchant.code,
        "name": merchant.name,
        "status": "ACTIVE",
        "approval_status": "APPROVED",
        "staff_type": "PRIMARY_MANAGER",
    }
    assert merchant_login["delivery_profile"] is None

    admin = await env.create_user(roles=("super_admin",))
    admin_login = await env.sign_in(ADMIN, admin.mobile_number)
    assert admin_login["role"] == "super_admin"
    assert admin_login["next_action"] == "OPEN_ADMIN_DASHBOARD"
    assert admin_login["merchant"] is None


async def test_response_headers_forbid_caching_and_carry_request_id(env):
    admin = await env.create_user(roles=("super_admin",))
    response = await env.request_code(ADMIN, admin.mobile_number)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    echoed = await env.client.post(f"{ADMIN}/otp/request", json={"mobile_number": admin.mobile_number}, headers={"X-Request-ID": "mobile-req-12345"})
    assert echoed.headers["x-request-id"] == "mobile-req-12345"
    unsafe = await env.client.get("/health", headers={"X-Request-ID": "bad id\r\n"})
    assert unsafe.headers["x-request-id"] != "bad id"


async def test_otp_code_rules(env):
    admin = await env.create_user(roles=("super_admin",))
    first = (await env.request_code(ADMIN, admin.mobile_number)).json()
    assert set(first) == {"request_id", "message", "expires_in", "resend_after", "code", "dev_otp"}
    # The plaintext code is only echoed under DEV_EXPOSE_OTP_IN_RESPONSE, which is off here.
    assert first["dev_otp"] is None
    assert TEST_OTP not in str(first)

    too_soon = await env.post(f"{ADMIN}/otp/resend", json={"request_id": first["request_id"]})
    _assert_error_envelope(too_soon, 429, "OTP_RESEND_TOO_SOON")

    second = (await env.request_code(ADMIN, admin.mobile_number)).json()
    superseded = await env.post(f"{ADMIN}/otp/verify", json={"request_id": first["request_id"], "otp": TEST_OTP})
    _assert_error_envelope(superseded, 400, "OTP_ALREADY_USED")

    wrong = await env.post(f"{ADMIN}/otp/verify", json={"request_id": second["request_id"], "otp": "0000"})
    _assert_error_envelope(wrong, 400, "OTP_INVALID")
    cross_channel = await env.post(f"{MERCHANT}/otp/verify", json={"request_id": second["request_id"], "otp": TEST_OTP})
    _assert_error_envelope(cross_channel, 400, "OTP_PURPOSE_MISMATCH")
    unknown = await env.post(f"{ADMIN}/otp/verify", json={"request_id": str(uuid4()), "otp": TEST_OTP})
    _assert_error_envelope(unknown, 400, "OTP_PURPOSE_MISMATCH")

    ok = await env.post(f"{ADMIN}/otp/verify", json={"request_id": second["request_id"], "otp": TEST_OTP})
    assert ok.status_code == 200
    replay = await env.post(f"{ADMIN}/otp/verify", json={"request_id": second["request_id"], "otp": TEST_OTP})
    _assert_error_envelope(replay, 400, "OTP_ALREADY_USED")


async def test_otp_attempt_limit_and_expiry(env):
    admin = await env.create_user(roles=("super_admin",))
    request_id = (await env.request_code(ADMIN, admin.mobile_number)).json()["request_id"]
    for _ in range(5):
        assert code_of(await env.post(f"{ADMIN}/otp/verify", json={"request_id": request_id, "otp": "0000"})) == "OTP_INVALID"
    locked = await env.post(f"{ADMIN}/otp/verify", json={"request_id": request_id, "otp": TEST_OTP})
    _assert_error_envelope(locked, 400, "OTP_ATTEMPTS_EXCEEDED")

    other = await env.create_user(roles=("super_admin",))
    request_id = (await env.request_code(ADMIN, other.mobile_number)).json()["request_id"]
    past = datetime.now(UTC) - timedelta(seconds=1)
    await env.execute(update(OtpChallenge).where(OtpChallenge.id == request_id).values(expires_at=past, resend_available_at=past))
    expired = await env.post(f"{ADMIN}/otp/verify", json={"request_id": request_id, "otp": TEST_OTP})
    _assert_error_envelope(expired, 400, "OTP_EXPIRED")
    resent = await env.post(f"{ADMIN}/otp/resend", json={"request_id": request_id})
    assert resent.status_code == 202
    assert (await env.post(f"{ADMIN}/otp/verify", json={"request_id": resent.json()["request_id"], "otp": TEST_OTP})).status_code == 200


async def test_hourly_request_limit(env):
    admin = await env.create_user(roles=("super_admin",))
    statuses = [(await env.request_code(ADMIN, admin.mobile_number)).status_code for _ in range(6)]
    assert statuses == [202] * 5 + [429]


async def test_validation_errors_list_fields(env):
    response = await env.post(f"{ADMIN}/otp/verify", json={"request_id": "x", "otp": 1234, "device": {"device_id": "d" * 101}})
    _assert_error_envelope(response, 422, "VALIDATION_ERROR")
    assert {item["field"] for item in response.json()["detail"]["fields"]} == {"otp", "device.device_id"}

    malformed = await env.client.post(f"{ADMIN}/otp/request", content=b"{bad", headers={"Content-Type": "application/json"})
    _assert_error_envelope(malformed, 422, "VALIDATION_ERROR")

    invalid_mobile = await env.request_code(ADMIN, "5876543210")
    _assert_error_envelope(invalid_mobile, 422, "INVALID_MOBILE_NUMBER")


async def test_error_envelope_for_each_status(env):
    missing = await env.get(f"{ADMIN}/me")
    _assert_error_envelope(missing, 401, "AUTH_REQUIRED")

    admin = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN, admin.mobile_number)
    await env.execute(update(User).where(User.id == admin.id).values(status="BLOCKED"))
    _assert_error_envelope(await env.get(f"{ADMIN}/me", login["token"]["access_token"]), 403, "ACCOUNT_BLOCKED")

    registration = await env.sign_in(REG, random_mobile())
    not_found = await env.get(f"{REG}/profile", registration["token"]["access_token"])
    _assert_error_envelope(not_found, 404, "REGISTRATION_PROFILE_NOT_FOUND")

    merchant = await env.create_merchant()
    mobile = random_mobile()
    onboarding = await env.sign_in(REG, mobile)
    token = onboarding["token"]["access_token"]
    await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code})
    conflict = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code})
    _assert_error_envelope(conflict, 409, "REGISTRATION_PROFILE_EXISTS")


async def test_legacy_sessions_without_channel_columns_keep_working(env):
    admin = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN, admin.mobile_number)
    session_id = jwt.decode(login["token"]["access_token"], options={"verify_signature": False})["session_id"]
    await env.execute(update(LoginSession).where(LoginSession.id == session_id).values(login_channel=None, session_type=None))

    assert (await env.get(f"{ADMIN}/me", login["token"]["access_token"])).status_code == 200
    refreshed = await env.post(f"{ADMIN}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    assert refreshed.status_code == 200
    new_session = await env.scalar(
        select(LoginSession).where(LoginSession.id == jwt.decode(refreshed.json()["access_token"], options={"verify_signature": False})["session_id"])
    )
    assert (new_session.login_channel, new_session.session_type) == ("ADMIN", "access")


async def test_refresh_keeps_device_and_rejects_garbage(env):
    driver, _, _ = await env.create_delivery_user()
    login = await env.sign_in(DELIVERY, driver.mobile_number, device_id="phone-1")
    refreshed = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    session_id = jwt.decode(refreshed.json()["access_token"], options={"verify_signature": False})["session_id"]
    assert (await env.scalar(select(LoginSession.device_id).where(LoginSession.id == session_id))) == "phone-1"

    _assert_error_envelope(await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": "garbage"}), 401, "TOKEN_INVALID")
    _assert_error_envelope(await env.post(f"{DELIVERY}/token/refresh", json={}), 422, "VALIDATION_ERROR")
    cross = await env.post(f"{MERCHANT}/token/refresh", json={"refresh_token": refreshed.json()["refresh_token"]})
    _assert_error_envelope(cross, 401, "TOKEN_CHANNEL_MISMATCH")
    access_as_refresh = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": refreshed.json()["access_token"]})
    _assert_error_envelope(access_as_refresh, 401, "TOKEN_TYPE_NOT_ALLOWED")


@pytest.mark.parametrize("body", [{}, {"refresh_token": "garbage"}, {"refresh_token": None}])
async def test_logout_is_idempotent(env, body):
    response = await env.post(f"{DELIVERY}/logout", json=body)
    assert response.status_code == 204


async def test_logout_ignores_other_apps_refresh_tokens(env):
    admin = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN, admin.mobile_number)
    assert (await env.post(f"{DELIVERY}/logout", json={"refresh_token": login["token"]["refresh_token"]})).status_code == 204
    assert (await env.get(f"{ADMIN}/me", login["token"]["access_token"])).status_code == 200
