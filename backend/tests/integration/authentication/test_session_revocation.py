"""A-01: access tokens stop working as soon as their session or account is no longer valid."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import update

from app.modules.authentication.models import LoginSession
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from tests.integration.authentication.conftest import code_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ADMIN = "/api/v1/admin/auth"
MERCHANT = "/api/v1/merchant/auth"
DELIVERY = "/api/v1/delivery/auth"


async def _staff(env, channel: str):
    if channel == "admin":
        return await env.create_user(roles=("super_admin",)), ADMIN
    if channel == "merchant":
        user, _ = await env.create_merchant_staff()
        return user, MERCHANT
    user, _, _ = await env.create_delivery_user()
    return user, DELIVERY


@pytest.mark.parametrize("channel", ["admin", "merchant", "delivery"])
async def test_access_token_stops_working_after_logout(env, channel):
    user, prefix = await _staff(env, channel)
    login = await env.sign_in(prefix, user.mobile_number)
    access, refresh = login["token"]["access_token"], login["token"]["refresh_token"]

    assert (await env.get(f"{prefix}/me", access)).status_code == 200
    assert (await env.post(f"{prefix}/logout", json={"refresh_token": refresh})).status_code == 204

    after = await env.get(f"{prefix}/me", access)
    assert after.status_code == 401
    assert code_of(after) == "SESSION_REVOKED"
    refreshed = await env.post(f"{prefix}/token/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 401
    assert code_of(refreshed) == "SESSION_REVOKED"


@pytest.mark.parametrize("channel", ["admin", "merchant", "delivery"])
async def test_old_access_token_fails_after_rotation(env, channel):
    user, prefix = await _staff(env, channel)
    login = await env.sign_in(prefix, user.mobile_number)

    rotated = await env.post(f"{prefix}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    assert rotated.status_code == 200

    old = await env.get(f"{prefix}/me", login["token"]["access_token"])
    assert old.status_code == 401
    assert code_of(old) == "SESSION_REVOKED"
    assert (await env.get(f"{prefix}/me", rotated.json()["access_token"])).status_code == 200


async def test_logout_all_ends_every_device_immediately(env):
    user, _ = await env.create_merchant_staff()
    device_a = await env.sign_in(MERCHANT, user.mobile_number, device_id="device-a")
    device_b = await env.sign_in(MERCHANT, user.mobile_number, device_id="device-b")
    protected = "/api/v1/merchant/delivery-users"

    assert (await env.get(protected, device_a["token"]["access_token"])).status_code == 200
    assert (await env.post(f"{MERCHANT}/logout-all", device_b["token"]["access_token"])).status_code == 204

    for login in (device_a, device_b):
        response = await env.get(protected, login["token"]["access_token"])
        assert response.status_code == 401
        assert code_of(response) == "SESSION_REVOKED"


async def test_logout_of_one_device_keeps_the_other_signed_in(env):
    user, _, _ = await env.create_delivery_user()
    device_a = await env.sign_in(DELIVERY, user.mobile_number, device_id="device-a")
    device_b = await env.sign_in(DELIVERY, user.mobile_number, device_id="device-b")

    await env.post(f"{DELIVERY}/logout", json={"refresh_token": device_a["token"]["refresh_token"]})

    assert (await env.get(f"{DELIVERY}/me", device_a["token"]["access_token"])).status_code == 401
    assert (await env.get(f"{DELIVERY}/me", device_b["token"]["access_token"])).status_code == 200


async def test_admin_block_stops_the_blocked_users_access(env):
    admin = await env.create_user(roles=("super_admin",))
    target = await env.create_user(roles=("super_admin",))
    admin_login = await env.sign_in(ADMIN, admin.mobile_number)
    target_login = await env.sign_in(ADMIN, target.mobile_number)

    blocked = await env.post(f"/api/v1/admin/users/{target.id}/block", admin_login["token"]["access_token"])
    assert blocked.status_code == 200

    for path in (f"{ADMIN}/me", "/api/v1/admin/roles"):
        response = await env.get(path, target_login["token"]["access_token"])
        assert response.status_code == 403
        assert code_of(response) == "ACCOUNT_BLOCKED"
    refresh = await env.post(f"{ADMIN}/token/refresh", json={"refresh_token": target_login["token"]["refresh_token"]})
    assert code_of(refresh) == "ACCOUNT_BLOCKED"


async def test_blocked_merchant_stops_staff_and_delivery_access(env):
    admin = await env.create_user(roles=("super_admin",))
    manager, merchant = await env.create_merchant_staff()
    driver, _, _ = await env.create_delivery_user(merchant)
    manager_login = await env.sign_in(MERCHANT, manager.mobile_number)
    driver_login = await env.sign_in(DELIVERY, driver.mobile_number)
    admin_login = await env.sign_in(ADMIN, admin.mobile_number)

    blocked = await env.post(f"/api/v1/admin/merchants/{merchant.id}/block", admin_login["token"]["access_token"])
    assert blocked.status_code == 200

    manager_me = await env.get(f"{MERCHANT}/me", manager_login["token"]["access_token"])
    assert (manager_me.status_code, code_of(manager_me)) == (403, "MERCHANT_BLOCKED")
    driver_me = await env.get(f"{DELIVERY}/me", driver_login["token"]["access_token"])
    assert (driver_me.status_code, code_of(driver_me)) == (403, "MERCHANT_BLOCKED")
    business = await env.get("/api/v1/merchant/delivery-users", manager_login["token"]["access_token"])
    assert (business.status_code, code_of(business)) == (403, "MERCHANT_BLOCKED")


async def test_helper_blocked_by_merchant_loses_access(env):
    manager, merchant = await env.create_merchant_staff()
    helper, _, profile = await env.create_delivery_user(merchant, kind="HELPER")
    manager_login = await env.sign_in(MERCHANT, manager.mobile_number)
    helper_login = await env.sign_in(DELIVERY, helper.mobile_number)

    blocked = await env.post(f"/api/v1/merchant/delivery-users/{profile.id}/block", manager_login["token"]["access_token"])
    assert blocked.status_code == 200

    response = await env.get(f"{DELIVERY}/me", helper_login["token"]["access_token"])
    assert response.status_code in (401, 403)
    assert code_of(response) in {"ACCOUNT_BLOCKED", "SESSION_REVOKED"}


async def test_token_error_codes(env):
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN, user.mobile_number)
    access, refresh = login["token"]["access_token"], login["token"]["refresh_token"]
    claims = jwt.decode(access, options={"verify_signature": False})

    missing = await env.get(f"{ADMIN}/me")
    assert (missing.status_code, code_of(missing)) == (401, "AUTH_REQUIRED")
    wrong_scheme = await env.get(f"{ADMIN}/me", headers={"Authorization": f"Token {access}"})
    assert code_of(wrong_scheme) == "AUTH_REQUIRED"
    assert code_of(await env.get(f"{ADMIN}/me", "not-a-token")) == "TOKEN_INVALID"
    assert code_of(await env.get(f"{ADMIN}/me", access[:-3] + "abc")) == "TOKEN_INVALID"
    assert code_of(await env.get(f"{ADMIN}/me", refresh)) == "TOKEN_TYPE_NOT_ALLOWED"
    assert code_of(await env.get(f"{MERCHANT}/me", access)) == "TOKEN_CHANNEL_MISMATCH"
    assert (await env.get(f"{ADMIN}/me", headers={"Authorization": f"bearer {access}"})).status_code == 200

    expired = jwt.encode(
        {**claims, "iat": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()), "exp": datetime.now(UTC) - timedelta(minutes=1)},
        env.settings.jwt_signing_secret,
        algorithm=env.settings.jwt_algorithm,
    )
    response = await env.get(f"{ADMIN}/me", expired)
    assert (response.status_code, code_of(response)) == (401, "TOKEN_EXPIRED")

    await env.execute(update(LoginSession).where(LoginSession.id == claims["session_id"]).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    response = await env.get(f"{ADMIN}/me", access)
    assert (response.status_code, code_of(response)) == (401, "SESSION_EXPIRED")


async def test_token_for_another_users_session_is_rejected(env):
    first = await env.create_user(roles=("super_admin",))
    second = await env.create_user(roles=("super_admin",))
    first_login = await env.sign_in(ADMIN, first.mobile_number)
    claims = jwt.decode(first_login["token"]["access_token"], options={"verify_signature": False})
    forged = jwt.encode({**claims, "sub": second.id}, env.settings.jwt_signing_secret, algorithm=env.settings.jwt_algorithm)

    response = await env.get(f"{ADMIN}/me", forged)
    assert (response.status_code, code_of(response)) == (401, "SESSION_REVOKED")


STATE_CASES = [
    ("inactive_user", "ACCOUNT_INACTIVE"),
    ("blocked_user", "ACCOUNT_BLOCKED"),
    ("no_role", "ROLE_NOT_ASSIGNED"),
    ("pending_merchant", "ACCOUNT_PENDING_APPROVAL"),
    ("rejected_merchant", "ACCOUNT_REJECTED"),
    ("blocked_merchant", "MERCHANT_BLOCKED"),
    ("inactive_merchant", "MERCHANT_INACTIVE"),
    ("blocked_staff_link", "ACCOUNT_BLOCKED"),
    ("pending_driver", "ACCOUNT_PENDING_APPROVAL"),
    ("rejected_driver", "ACCOUNT_REJECTED"),
    ("blocked_driver", "ACCOUNT_BLOCKED"),
    ("driver_of_blocked_merchant", "MERCHANT_BLOCKED"),
]
MERCHANT_CASES = {"pending_merchant", "rejected_merchant", "blocked_merchant", "inactive_merchant", "blocked_staff_link"}


async def _eligible_account(env, setup: str):
    """An account that may sign in now, plus the change (setup) that makes it ineligible."""
    if setup in {"inactive_user", "blocked_user", "no_role"}:
        user = await env.create_user(roles=("super_admin",))
        changes = {
            "inactive_user": update(User).where(User.id == user.id).values(status="INACTIVE"),
            "blocked_user": update(User).where(User.id == user.id).values(status="BLOCKED"),
            "no_role": update(UserRole).where(UserRole.user_id == user.id).values(is_active=False),
        }
        return user, ADMIN, changes[setup]
    if setup in MERCHANT_CASES:
        user, merchant = await env.create_merchant_staff()
        changes = {
            "pending_merchant": update(Merchant).where(Merchant.id == merchant.id).values(approval_status="PENDING"),
            "rejected_merchant": update(Merchant).where(Merchant.id == merchant.id).values(approval_status="REJECTED"),
            "blocked_merchant": update(Merchant).where(Merchant.id == merchant.id).values(status="BLOCKED"),
            "inactive_merchant": update(Merchant).where(Merchant.id == merchant.id).values(status="INACTIVE"),
            "blocked_staff_link": update(MerchantUser).where(MerchantUser.user_id == user.id).values(status="BLOCKED"),
        }
        return user, MERCHANT, changes[setup]
    user, merchant, profile = await env.create_delivery_user()
    changes = {
        "pending_driver": update(DeliveryProfile).where(DeliveryProfile.id == profile.id).values(approval_status="PENDING"),
        "rejected_driver": update(DeliveryProfile).where(DeliveryProfile.id == profile.id).values(approval_status="REJECTED"),
        "blocked_driver": update(DeliveryProfile).where(DeliveryProfile.id == profile.id).values(status="BLOCKED"),
        "driver_of_blocked_merchant": update(Merchant).where(Merchant.id == merchant.id).values(status="BLOCKED"),
    }
    return user, DELIVERY, changes[setup]


@pytest.mark.parametrize(("setup", "expected"), STATE_CASES)
async def test_account_state_change_after_sign_in_is_enforced(env, setup, expected):
    user, prefix, change = await _eligible_account(env, setup)
    login = await env.sign_in(prefix, user.mobile_number)
    await env.execute(change)

    me = await env.get(f"{prefix}/me", login["token"]["access_token"])
    assert (me.status_code, code_of(me)) == (403, expected)
    refresh = await env.post(f"{prefix}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    assert (refresh.status_code, code_of(refresh)) == (403, expected)


@pytest.mark.parametrize(("setup", "expected"), STATE_CASES + [("manager_on_delivery_app", "ROLE_NOT_ASSIGNED")])
async def test_ineligible_accounts_are_refused_a_code(env, setup, expected):
    if setup == "manager_on_delivery_app":
        (user, _), prefix = await env.create_merchant_staff(), DELIVERY
    else:
        user, prefix, change = await _eligible_account(env, setup)
        await env.execute(change)

    # The request is refused outright: no challenge is created and no code is sent.
    request = await env.request_code(prefix, user.mobile_number)
    assert (request.status_code, code_of(request)) == (403, expected)
    assert env.sent_to(user.mobile_number) == 0


async def test_account_blocked_between_request_and_verify_is_reported(env):
    user = await env.create_user(roles=("super_admin",))
    request = await env.request_code(ADMIN, user.mobile_number)
    await env.execute(update(User).where(User.id == user.id).values(status="BLOCKED"))

    verify = await env.post(f"{ADMIN}/otp/verify", json={"request_id": request.json()["request_id"], "otp": env.last_code()})
    assert (verify.status_code, code_of(verify)) == (403, "ACCOUNT_BLOCKED")
    replay = await env.post(f"{ADMIN}/otp/verify", json={"request_id": request.json()["request_id"], "otp": env.last_code()})
    assert code_of(replay) == "OTP_ALREADY_USED"
