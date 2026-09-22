"""A-02, A-03, A-04, A-05: customer onboarding session scope, ownership and the registration-to-login journey."""

import asyncio

import pytest
from sqlalchemy import update

from app.modules.authentication.account_state import CUSTOMER_UNDER_REVIEW
from app.modules.customers.models import CustomerDocument
from app.modules.users.models import User
from tests.integration.authentication.conftest import code_of, random_mobile

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

REG = "/api/v1/customer/registration"
CUSTOMER = "/api/v1/customer/auth"
MERCHANT = "/api/v1/merchant/auth"
REVIEWER_ROLE = "test_customer_reviewer"
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


async def _register(env, mobile: str | None = None) -> tuple[str, dict]:
    mobile = mobile or random_mobile()
    return mobile, await env.sign_in(REG, mobile)


async def _reviewer(env, merchant=None):
    await env.create_role(REVIEWER_ROLE, "MERCHANT", ["customers.view", "customers.approve", "customers.reject"])
    user, merchant = await env.create_merchant_staff(merchant, roles=("manager", REVIEWER_ROLE))
    login = await env.sign_in(MERCHANT, user.mobile_number)
    return login["token"]["access_token"], merchant


async def _submitted_customer(env, merchant) -> tuple[str, dict, str]:
    mobile, registration = await _register(env)
    token = registration["token"]["access_token"]
    documents = []
    for document_type, number in (("AADHAAR", "123412341234"), ("PAN", "ABCDE1234F")):
        uploaded = await env.client.post(
            "/api/v1/customer/documents",
            files={"file": ("scan.pdf", PDF_BYTES, "application/pdf")},
            data={"type": document_type},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert uploaded.status_code == 201, uploaded.text
        documents.append({"type": document_type, "number": number, "fileName": uploaded.json()["fileId"]})
    created = await env.post(
        f"{REG}/profile",
        token,
        json={
            "merchant_code": merchant.code,
            "customerType": "RETAIL",
            "businessName": "Sharma Stores",
            "ownerName": "Ravi Sharma",
            "deliveryAddress": {
                "line1": "12 MG Road",
                "city": "Indore",
                "state": "Madhya Pradesh",
                "pincode": "452001",
            },
            "documents": documents,
        },
    )
    assert created.status_code == 201, created.text
    submitted = await env.post(f"{REG}/submit", token)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == CUSTOMER_UNDER_REVIEW
    await env.execute(update(CustomerDocument).where(CustomerDocument.customer_id == created.json()["id"]).values(scan_status="CLEAN"))
    return mobile, registration, created.json()["id"]


async def test_registration_verify_returns_restricted_onboarding_session(env):
    mobile, first = await _register(env)
    assert first["session_type"] == "onboarding"
    assert first["is_new_user"] is True
    assert first["next_action"] == "COMPLETE_PROFILE"
    assert first["user_type"] == "CUSTOMER"
    assert first["profile_completion_status"] == "NOT_STARTED"

    _, second = await _register(env, mobile)
    assert second["is_new_user"] is False
    assert second["user_id"] == first["user_id"]


async def test_onboarding_token_is_rejected_on_full_customer_and_other_routes(env):
    _, registration = await _register(env)
    token = registration["token"]["access_token"]

    assert (await env.get(f"{REG}/me", token)).status_code == 200
    for path in (f"{CUSTOMER}/me", "/api/v1/merchant/delivery-users", "/api/v1/admin/roles"):
        response = await env.get(path, token)
        assert response.status_code == 401, path
        assert code_of(response) in {"TOKEN_TYPE_NOT_ALLOWED", "TOKEN_CHANNEL_MISMATCH"}
    logout_all = await env.post(f"{CUSTOMER}/logout-all", token)
    assert code_of(logout_all) == "TOKEN_TYPE_NOT_ALLOWED"


async def test_registration_routes_require_an_onboarding_session(env):
    merchant = await env.create_merchant()
    no_token = await env.post(f"{REG}/profile", json={"merchant_code": merchant.code})
    assert (no_token.status_code, code_of(no_token)) == (401, "AUTH_REQUIRED")
    status_no_token = await env.get(f"{REG}/status", params={"mobile_number": "9876543210"})
    assert (status_no_token.status_code, code_of(status_no_token)) == (401, "AUTH_REQUIRED")

    staff = await env.create_user(roles=("super_admin",))
    admin_login = await env.sign_in("/api/v1/admin/auth", staff.mobile_number)
    wrong = await env.post(f"{REG}/profile", admin_login["token"]["access_token"], json={"merchant_code": merchant.code})
    assert wrong.status_code == 401
    assert code_of(wrong) == "TOKEN_CHANNEL_MISMATCH"


async def test_profile_belongs_to_the_verified_number(env):
    merchant = await env.create_merchant()
    mobile, registration = await _register(env)
    token = registration["token"]["access_token"]

    other = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, "mobile_number": "9123456780"})
    assert (other.status_code, code_of(other)) == (403, "PERMISSION_DENIED")

    created = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code, "mobile_number": mobile[3:]})
    assert created.status_code == 201
    stored = await env.customer_profile(mobile)
    assert stored.user_id == registration["user_id"]
    assert stored.mobile_verified_at is not None

    duplicate = await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code})
    assert (duplicate.status_code, code_of(duplicate)) == (409, "REGISTRATION_PROFILE_EXISTS")


async def test_concurrent_profile_creation_creates_one_profile(env):
    merchant = await env.create_merchant()
    _, registration = await _register(env)
    token = registration["token"]["access_token"]

    responses = await asyncio.gather(*(env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code}) for _ in range(3)))

    assert sorted(r.status_code for r in responses) == [201, 409, 409]
    assert all(code_of(r) == "REGISTRATION_PROFILE_EXISTS" for r in responses if r.status_code == 409)


async def test_applicants_only_see_their_own_status(env):
    merchant = await env.create_merchant()
    _, first = await _register(env)
    await env.post(f"{REG}/profile", first["token"]["access_token"], json={"merchant_code": merchant.code})
    _, second = await _register(env)

    # The mobile_number query parameter is ignored: status always comes from the session.
    response = await env.get(f"{REG}/status", second["token"]["access_token"], params={"mobile_number": "0000"})
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_STARTED"
    assert response.json()["next_action"] == "COMPLETE_PROFILE"
    assert (await env.get(f"{REG}/profile", second["token"]["access_token"])).status_code == 404


async def test_invalid_merchant_code_and_incomplete_submission(env):
    _, registration = await _register(env)
    token = registration["token"]["access_token"]

    invalid = await env.post(f"{REG}/profile", token, json={"merchant_code": "NO-SUCH-CODE"})
    assert (invalid.status_code, code_of(invalid)) == (422, "MERCHANT_CODE_INVALID")
    assert invalid.json()["detail"]["fields"][0]["field"] == "merchant_code"

    merchant = await env.create_merchant()
    assert (await env.post(f"{REG}/profile", token, json={"merchant_code": merchant.code})).status_code == 201
    incomplete = await env.post(f"{REG}/submit", token)
    assert (incomplete.status_code, code_of(incomplete)) == (422, "REGISTRATION_INCOMPLETE")
    assert {item["field"] for item in incomplete.json()["detail"]["fields"]} == {"name", "customer_type"}

    bad_type = await env.client.patch(f"{REG}/profile", json={"customer_type": "WHOLESALE"}, headers={"Authorization": f"Bearer {token}"})
    assert (bad_type.status_code, code_of(bad_type)) == (422, "VALIDATION_ERROR")


async def test_onboarding_refresh_rotates_and_stays_restricted(env):
    _, registration = await _register(env)
    refreshed = await env.post(f"{REG}/token/refresh", json={"refresh_token": registration["token"]["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["access_token"]

    me = await env.get(f"{REG}/me", new_access)
    assert me.status_code == 200
    assert me.json()["session_type"] == "onboarding"
    assert code_of(await env.get(f"{CUSTOMER}/me", new_access)) == "TOKEN_TYPE_NOT_ALLOWED"

    reuse = await env.post(f"{REG}/token/refresh", json={"refresh_token": registration["token"]["refresh_token"]})
    assert reuse.status_code == 401
    # An onboarding refresh token cannot be exchanged on the full customer route.
    cross = await env.post(f"{CUSTOMER}/token/refresh", json={"refresh_token": refreshed.json()["refresh_token"]})
    assert (cross.status_code, code_of(cross)) == (401, "TOKEN_TYPE_NOT_ALLOWED")


async def test_customer_registration_to_login_journey(env):
    reviewer_token, merchant = await _reviewer(env)
    mobile, registration, customer_id = await _submitted_customer(env, merchant)

    status_response = await env.get(f"{REG}/status", registration["token"]["access_token"])
    assert status_response.json()["next_action"] == "WAIT_FOR_APPROVAL"
    # Not yet approved: the sign-in request is refused directly and no code is sent.
    pending_request = await env.request_code(CUSTOMER, mobile)
    assert (pending_request.status_code, code_of(pending_request)) == (403, "ACCOUNT_PENDING_APPROVAL")
    assert env.sent_to(mobile) == 1  # only the registration code

    queue = await env.get("/api/v1/merchant/customers", reviewer_token)
    assert customer_id in [item["id"] for item in queue.json()["items"]]
    approved = await env.post(f"/api/v1/merchant/customers/{customer_id}/approve", reviewer_token)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    again = await env.post(f"/api/v1/merchant/customers/{customer_id}/approve", reviewer_token)
    assert (again.status_code, code_of(again)) == (409, "INVALID_STATUS_TRANSITION")

    onboarding_status = await env.get(f"{REG}/status", registration["token"]["access_token"])
    assert onboarding_status.json()["next_action"] == "SIGN_IN"
    onboarding_me = await env.get(f"{REG}/me", registration["token"]["access_token"])
    assert onboarding_me.json()["next_action"] == "SIGN_IN"

    login = await env.sign_in(CUSTOMER, mobile)
    assert login["session_type"] == "access"
    assert login["next_action"] == "OPEN_CUSTOMER_HOME"
    assert login["role"] == "customer"
    assert login["customer_profile"]["status"] == "APPROVED"

    me = await env.get(f"{CUSTOMER}/me", login["token"]["access_token"])
    assert me.status_code == 200
    assert me.json()["account_status"] == "ACTIVE"
    # A full customer session is not accepted on onboarding-only routes.
    assert code_of(await env.get(f"{REG}/status", login["token"]["access_token"])) == "TOKEN_TYPE_NOT_ALLOWED"

    refreshed = await env.post(f"{CUSTOMER}/token/refresh", json={"refresh_token": login["token"]["refresh_token"]})
    assert refreshed.status_code == 200
    assert (await env.post(f"{CUSTOMER}/logout", json={"refresh_token": refreshed.json()["refresh_token"]})).status_code == 204
    revoked = await env.get(f"{CUSTOMER}/me", refreshed.json()["access_token"])
    assert (revoked.status_code, code_of(revoked)) == (401, "SESSION_REVOKED")


async def test_rejected_customer_can_correct_and_resubmit(env):
    reviewer_token, merchant = await _reviewer(env)
    mobile, registration, customer_id = await _submitted_customer(env, merchant)
    token = registration["token"]["access_token"]

    missing_reason = await env.post(f"/api/v1/merchant/customers/{customer_id}/reject", reviewer_token, json={})
    assert missing_reason.status_code == 422
    rejected = await env.post(f"/api/v1/merchant/customers/{customer_id}/reject", reviewer_token, json={"reason": "GST number does not match"})
    assert rejected.status_code == 200

    status_response = (await env.get(f"{REG}/status", token)).json()
    assert status_response["status"] == "REJECTED"
    assert status_response["rejection_reason"] == "GST number does not match"
    assert status_response["next_action"] == "COMPLETE_PROFILE"
    sent_before = env.sent_to(mobile)
    login = await env.request_code(CUSTOMER, mobile)
    assert (login.status_code, code_of(login)) == (403, "ACCOUNT_REJECTED")
    assert env.sent_to(mobile) == sent_before

    updated = await env.client.patch(f"{REG}/profile", json={"gst_number": "27ABCDE1234F1Z5"}, headers={"Authorization": f"Bearer {token}"})
    assert updated.status_code == 200
    resubmitted = await env.post(f"{REG}/submit", token)
    assert resubmitted.json()["status"] == CUSTOMER_UNDER_REVIEW


async def test_review_is_limited_to_the_reviewers_merchant_and_permissions(env):
    _, merchant = await _reviewer(env)
    other_token, _ = await _reviewer(env)
    _, _, customer_id = await _submitted_customer(env, merchant)

    foreign = await env.post(f"/api/v1/merchant/customers/{customer_id}/approve", other_token)
    assert (foreign.status_code, code_of(foreign)) == (404, "CUSTOMER_NOT_FOUND")

    plain_manager, _ = await env.create_merchant_staff(merchant)
    plain_login = await env.sign_in(MERCHANT, plain_manager.mobile_number)
    denied = await env.post(f"/api/v1/merchant/customers/{customer_id}/approve", plain_login["token"]["access_token"])
    assert (denied.status_code, code_of(denied)) == (403, "PERMISSION_DENIED")


async def test_approved_profile_can_no_longer_be_edited(env):
    reviewer_token, merchant = await _reviewer(env)
    _, registration, customer_id = await _submitted_customer(env, merchant)
    await env.post(f"/api/v1/merchant/customers/{customer_id}/approve", reviewer_token)

    response = await env.client.patch(
        f"{REG}/profile",
        json={"name": "Changed"},
        headers={"Authorization": f"Bearer {registration['token']['access_token']}"},
    )
    assert (response.status_code, code_of(response)) == (409, "REGISTRATION_NOT_EDITABLE")


async def test_blocked_user_cannot_hold_an_onboarding_session(env):
    blocked = await env.create_user(status="BLOCKED")
    response = await env.request_code(REG, blocked.mobile_number)
    assert (response.status_code, code_of(response)) == (403, "ACCOUNT_BLOCKED")
    assert env.sent_to(blocked.mobile_number) == 0

    user = await env.create_user(status="PENDING")
    _, registration = await _register(env, user.mobile_number)
    await env.execute(update(User).where(User.id == user.id).values(status="BLOCKED"))
    status_response = await env.get(f"{REG}/status", registration["token"]["access_token"])
    assert (status_response.status_code, code_of(status_response)) == (403, "ACCOUNT_BLOCKED")
