"""A-07, A-09, A-10, A-18: refresh-token reuse, request limits, enumeration resistance and audit events."""

import asyncio

import jwt
import pytest
from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from tests.integration.authentication.conftest import (
    TEST_OTP,
    code_of,
    new_client,
    random_ip,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ADMIN = "/api/v1/admin/auth"
DELIVERY = "/api/v1/delivery/auth"
CUSTOMER = "/api/v1/customer/auth"
REG = "/api/v1/customer/registration"


def _session_id(token: str) -> str:
    return jwt.decode(token, options={"verify_signature": False})["session_id"]


@pytest.fixture
def settings_overrides(request) -> dict:
    return getattr(request, "param", {})


@pytest.mark.parametrize("settings_overrides", [{"refresh_reuse_grace_seconds": 0}], indirect=True)
async def test_replayed_refresh_token_revokes_the_whole_sign_in(env):
    driver, _, _ = await env.create_delivery_user()
    login = await env.sign_in(DELIVERY, driver.mobile_number)
    first = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    second = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": first.json()["refresh_token"]})
    assert second.status_code == 200
    other_device = await env.sign_in(DELIVERY, driver.mobile_number, device_id="other-phone")

    replay = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    assert (replay.status_code, code_of(replay)) == (401, "SESSION_REVOKED")

    current = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": second.json()["refresh_token"]})
    assert (current.status_code, code_of(current)) == (401, "SESSION_REVOKED")
    assert code_of(await env.get(f"{DELIVERY}/me", second.json()["access_token"])) == "SESSION_REVOKED"
    # Other sign-ins of the same user are not part of the family and keep working.
    assert (await env.get(f"{DELIVERY}/me", other_device["token"]["access_token"])).status_code == 200

    family = await env.scalar(select(LoginSession).where(LoginSession.id == _session_id(second.json()["access_token"])))
    assert family.revoked_reason == "REFRESH_TOKEN_REUSED"
    assert family.family_id == _session_id(login["token"]["access_token"])
    event = await env.scalar(select(AuditLog).where(AuditLog.event_type == "auth.refresh_token_reuse_detected", AuditLog.actor_user_id == driver.id))
    assert event is not None and event.result == "FAILURE"


async def test_concurrent_refresh_keeps_the_winner_signed_in(env):
    driver, _, _ = await env.create_delivery_user()
    login = await env.sign_in(DELIVERY, driver.mobile_number)
    body = {"refresh_token": login["token"]["refresh_token"]}

    responses = await asyncio.gather(*(env.post(f"{DELIVERY}/token/refresh", json=body) for _ in range(3)))

    assert sorted(r.status_code for r in responses) == [200, 401, 401]
    winner = next(r for r in responses if r.status_code == 200).json()
    # A replay inside the grace window does not revoke the new session.
    assert (await env.get(f"{DELIVERY}/me", winner["access_token"])).status_code == 200
    assert (await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": winner["refresh_token"]})).status_code == 200


async def test_unknown_numbers_are_rejected_with_an_explicit_error(env):
    """Unregistered numbers are reported directly so the apps can show a sign-up prompt.

    This deliberately makes the endpoint disclose whether a number has an account.
    """
    admin = await env.create_user(roles=("super_admin",))
    known = await env.request_code(ADMIN, admin.mobile_number)
    unknown_mobile = random_mobile()
    unknown = await env.request_code(ADMIN, unknown_mobile)

    assert known.status_code == 202
    assert (unknown.status_code, code_of(unknown)) == (404, "NUMBER_NOT_REGISTERED")
    assert env.sent_to(admin.mobile_number) == 1
    assert env.sent_to(unknown_mobile) == 0
    # No challenge row exists, so there is nothing to verify or resend against.
    assert "request_id" not in unknown.json()
    async with env.sessions() as db:
        stored = list((await db.execute(select(OtpChallenge).where(OtpChallenge.mobile_number == unknown_mobile))).scalars())
    assert stored == []


@pytest.mark.parametrize("settings_overrides", [{"otp_request_limit_per_ip": 3}], indirect=True)
async def test_code_requests_are_limited_per_client_ip(env):
    # The per-IP limit is applied before the account is looked up, so unregistered numbers count too.
    statuses = [(await env.request_code(ADMIN, random_mobile())).status_code for _ in range(3)]
    limited = await env.request_code(ADMIN, random_mobile())

    assert statuses == [404, 404, 404]
    assert (limited.status_code, code_of(limited)) == (429, "OTP_RATE_LIMITED")
    assert 0 < int(limited.headers["retry-after"]) <= 3600
    async with new_client(random_ip()) as other:
        assert (await other.post(f"{ADMIN}/otp/request", json={"mobile_number": random_mobile()})).status_code == 404


@pytest.mark.parametrize("settings_overrides", [{"otp_request_limit_per_ip": 2, "trusted_proxy_ips": ["198.51.0.0/16"]}], indirect=True)
async def test_forwarded_client_ip_is_used_behind_a_trusted_proxy(env):
    for _ in range(2):
        response = await env.client.post(f"{ADMIN}/otp/request", json={"mobile_number": random_mobile()}, headers={"X-Forwarded-For": "203.0.113.7"})
        assert response.status_code == 404
    limited = await env.client.post(f"{ADMIN}/otp/request", json={"mobile_number": random_mobile()}, headers={"X-Forwarded-For": "203.0.113.7"})
    assert limited.status_code == 429
    other_client = await env.client.post(f"{ADMIN}/otp/request", json={"mobile_number": random_mobile()}, headers={"X-Forwarded-For": "203.0.113.8"})
    assert other_client.status_code == 404


@pytest.mark.parametrize("settings_overrides", [{"otp_request_limit_per_device": 2}], indirect=True)
async def test_code_requests_are_limited_per_device(env):
    device = {"device_id": "install-abc", "device_type": "android"}
    for _ in range(2):
        assert (await env.request_code(DELIVERY, random_mobile(), device=device)).status_code == 404
    limited = await env.request_code(DELIVERY, random_mobile(), device=device)
    assert (limited.status_code, code_of(limited)) == (429, "OTP_RATE_LIMITED")


@pytest.mark.parametrize("settings_overrides", [{"check_mobile_limit_per_ip": 2}], indirect=True)
async def test_check_mobile_is_limited_per_client_ip(env):
    for _ in range(2):
        assert (await env.post(f"{CUSTOMER}/check-mobile", json={"mobile_number": random_mobile()})).status_code == 200
    limited = await env.post(f"{CUSTOMER}/check-mobile", json={"mobile_number": random_mobile()})
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")
    assert "retry-after" in limited.headers


@pytest.mark.parametrize("settings_overrides", [{"otp_verify_limit_per_ip": 3}], indirect=True)
async def test_code_verification_is_limited_per_client_ip(env):
    for _ in range(3):
        await env.post(f"{ADMIN}/otp/verify", json={"request_id": "unknown", "otp": "0000"})
    limited = await env.post(f"{ADMIN}/otp/verify", json={"request_id": "unknown", "otp": "0000"})
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")


@pytest.mark.parametrize("settings_overrides", [{"otp_max_failed_attempts_per_hour": 3, "otp_resend_cooldown_seconds": 0}], indirect=True)
async def test_wrong_codes_across_requests_lock_the_number(env):
    admin = await env.create_user(roles=("super_admin",))
    first = (await env.request_code(ADMIN, admin.mobile_number)).json()["request_id"]
    for _ in range(2):
        await env.post(f"{ADMIN}/otp/verify", json={"request_id": first, "otp": "0000"})
    second = (await env.request_code(ADMIN, admin.mobile_number)).json()["request_id"]
    assert code_of(await env.post(f"{ADMIN}/otp/verify", json={"request_id": second, "otp": "0000"})) == "OTP_INVALID"

    locked_verify = await env.post(f"{ADMIN}/otp/verify", json={"request_id": second, "otp": TEST_OTP})
    assert (locked_verify.status_code, code_of(locked_verify)) == (429, "OTP_LOCKED")
    locked_request = await env.request_code(ADMIN, admin.mobile_number)
    assert (locked_request.status_code, code_of(locked_request)) == (429, "OTP_LOCKED")
    assert int(locked_request.headers["retry-after"]) > 0


async def test_resend_too_soon_reports_the_wait(env):
    admin = await env.create_user(roles=("super_admin",))
    request_id = (await env.request_code(ADMIN, admin.mobile_number)).json()["request_id"]
    response = await env.post(f"{ADMIN}/otp/resend", json={"request_id": request_id})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 30


async def test_authentication_events_are_audited_without_secrets(env):
    driver, _, _ = await env.create_delivery_user()
    login = await env.sign_in(DELIVERY, driver.mobile_number, device_id="audit-phone")
    await env.post(f"{DELIVERY}/otp/verify", json={"request_id": "unknown", "otp": "0000"})
    refreshed = await env.post(f"{DELIVERY}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    await env.post(f"{DELIVERY}/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
    unknown_mobile = random_mobile()
    await env.request_code(DELIVERY, unknown_mobile)

    async with env.sessions() as db:
        rows = list((await db.execute(select(AuditLog).where(AuditLog.event_type.like("auth.%")))).scalars())
    mine = [row for row in rows if row.actor_user_id == driver.id or row.masked_mobile == f"******{driver.mobile_number[-4:]}"]
    events = {row.event_type for row in mine}
    assert {
        "auth.otp_requested",
        "auth.otp_verification_succeeded",
        "auth.login_succeeded",
        "auth.token_refreshed",
        "auth.logout",
    } <= events
    assert any(row.event_type == "auth.otp_verification_failed" and row.reason_code == "OTP_PURPOSE_MISMATCH" for row in rows)
    rejected = [row for row in rows if row.masked_mobile == f"******{unknown_mobile[-4:]}" and row.event_type == "auth.otp_request_rejected"]
    assert rejected and rejected[-1].reason_code == "NUMBER_NOT_REGISTERED" and rejected[-1].result == "FAILURE"

    secrets = [login["token"]["access_token"], login["token"]["refresh_token"], TEST_OTP, driver.mobile_number, driver.mobile_number[3:], "audit-phone"]
    for row in rows:
        stored = " ".join(str(value) for value in (row.message, row.reason_code, row.masked_mobile, row.device_hash, row.entity_id) if value)
        assert not any(secret in stored for secret in secrets)
    login_row = next(row for row in mine if row.event_type == "auth.login_succeeded")
    assert login_row.login_channel == "DELIVERY"
    assert login_row.ip_address and login_row.device_hash and len(login_row.device_hash) == 64


async def test_sessions_record_client_details(env):
    admin = await env.create_user(roles=("super_admin",))
    response = await env.client.post(f"{ADMIN}/otp/request", json={"mobile_number": admin.mobile_number}, headers={"User-Agent": "MBGA-Android/1.0"})
    verify = await env.post(f"{ADMIN}/otp/verify", json={"request_id": response.json()["request_id"], "otp": TEST_OTP}, headers={"User-Agent": "MBGA-Android/1.0"})
    session = await env.scalar(select(LoginSession).where(LoginSession.id == _session_id(verify.json()["token"]["access_token"])))
    assert session.user_agent == "MBGA-Android/1.0"
    assert session.ip_address.startswith("198.51.")
