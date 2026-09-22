"""Every login channel dispatches through the one shared provider — and only when it should.

No real SMS is sent anywhere in this file. The provider is a capturing fake, so these tests
prove the *wiring*: which requests reach a provider, how many times, and what happens to the
authentication contract when delivery fails.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.modules.authentication.otp_models import OtpChallenge
from app.modules.customers.models import CustomerDocument
from app.shared.otp.provider import OTPDeliveryError
from tests.integration.authentication.conftest import code_of, random_mobile
from tests.integration.sms.conftest import ADMIN, CUSTOMER, DELIVERY, MERCHANT, REGISTRATION

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

# A minimal real PDF, so the upload passes the file-signature check rather than being mocked.
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


async def merchant_staff(env):
    user, _ = await env.create_merchant_staff()
    return user.mobile_number


async def delivery_rider(env):
    user, _, _ = await env.create_delivery_user()
    return user.mobile_number


async def admin_user(env):
    user = await env.create_user(roles=("super_admin",), name="Test Admin")
    return user.mobile_number


# --- one dispatch per channel ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "account"),
    [
        (MERCHANT, merchant_staff),
        (DELIVERY, delivery_rider),
        (ADMIN, admin_user),
    ],
)
async def test_each_staff_channel_dispatches_exactly_once(env, prefix, account):
    mobile = await account(env)
    before = len(env.provider.sent)

    response = await env.request_code(prefix, mobile)
    assert response.status_code == 202, response.text

    dispatched = env.provider.sent[before:]
    assert len(dispatched) == 1
    assert dispatched[0]["mobile_number"] == mobile
    # The provider receives the code the backend generated; it never makes one.
    assert dispatched[0]["otp"].isdigit()


async def test_customer_registration_dispatches_once(env):
    mobile = random_mobile()
    response = await env.request_code(REGISTRATION, mobile)
    assert response.status_code == 202, response.text
    assert env.sent_to(mobile) == 1


async def test_customer_login_dispatches_for_an_eligible_account(env):
    """Customer login follows the existing eligibility policy, unchanged by this work."""
    reviewer_role = f"sms_reviewer_{random_mobile()[-6:]}"
    await env.create_role(reviewer_role, "MERCHANT", ["customers.view", "customers.approve"])
    staff, merchant = await env.create_merchant_staff(roles=("manager", reviewer_role))
    reviewer = (await env.sign_in(MERCHANT, staff.mobile_number))["token"]["access_token"]

    mobile = random_mobile()
    registration = await env.sign_in(REGISTRATION, mobile)
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
        f"{REGISTRATION}/profile",
        token,
        json={
            "merchant_code": merchant.code,
            "customerType": "RETAIL",
            "businessName": "Sharma Stores",
            "ownerName": "Ravi Sharma",
            "deliveryAddress": {"line1": "12 MG Road", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001"},
            "documents": documents,
        },
    )
    assert created.status_code == 201, created.text
    assert (await env.post(f"{REGISTRATION}/submit", token)).status_code == 200
    await env.execute(
        update(CustomerDocument)
        .where(CustomerDocument.customer_id == created.json()["id"])
        .values(scan_status="CLEAN")
    )
    approved = await env.post(f"/api/v1/merchant/customers/{created.json()['id']}/approve", reviewer)
    assert approved.status_code == 200, approved.text

    before = env.sent_to(mobile)
    response = await env.request_code(CUSTOMER, mobile)
    assert response.status_code == 202, response.text
    assert env.sent_to(mobile) == before + 1


async def test_a_resend_dispatches_once_more(env):
    mobile = await merchant_staff(env)
    request = await env.request_code(MERCHANT, mobile)
    assert request.status_code == 202, request.text
    request_id = request.json()["request_id"]

    # The resend cooldown is real; move the challenge's clock back rather than sleeping.
    await env.execute(
        OtpChallenge.__table__.update()
        .where(OtpChallenge.id == request_id)
        .values(resend_available_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    before = env.sent_to(mobile)
    resend = await env.client.post(f"{MERCHANT}/otp/resend", json={"request_id": request_id})
    assert resend.status_code == 202, resend.text
    assert env.sent_to(mobile) == before + 1


# --- requests that must never reach the provider ---------------------------------------------


async def test_verify_refresh_and_logout_never_dispatch(env):
    mobile = await merchant_staff(env)
    login = await env.sign_in(MERCHANT, mobile)
    access, refresh = login["token"]["access_token"], login["token"]["refresh_token"]
    before = len(env.provider.sent)

    assert (await env.get(f"{MERCHANT}/me", access)).status_code == 200
    refreshed = await env.client.post(f"{MERCHANT}/token/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200, refreshed.text
    assert (
        await env.client.post(f"{MERCHANT}/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
    ).status_code == 204
    assert (await env.post(f"{MERCHANT}/logout-all", access)).status_code in {200, 204, 401}

    # Only the two sign-in sends from `sign_in` happened; nothing after them dispatched.
    assert len(env.provider.sent) == before


async def test_an_unregistered_number_costs_no_message(env):
    """The vendor bills per message, so an unknown number must not reach it."""
    before = len(env.provider.sent)
    response = await env.request_code(MERCHANT, random_mobile())
    assert (response.status_code, code_of(response)) == (404, "NUMBER_NOT_REGISTERED")
    assert len(env.provider.sent) == before


async def test_a_blocked_account_costs_no_message(env):
    blocked = await env.create_user(status="BLOCKED", roles=("manager",))
    before = len(env.provider.sent)
    response = await env.request_code(MERCHANT, blocked.mobile_number)
    assert response.status_code == 403
    assert len(env.provider.sent) == before


async def test_a_wrong_channel_account_costs_no_message(env):
    """A delivery rider asking for an admin code must not trigger a send."""
    mobile = await delivery_rider(env)
    before = len(env.provider.sent)
    response = await env.request_code(ADMIN, mobile)
    assert response.status_code in {403, 404}
    assert len(env.provider.sent) == before


async def test_a_rate_limited_request_costs_no_message(env):
    mobile = await merchant_staff(env)
    limit = env.settings.otp_max_requests_per_hour
    for _ in range(limit):
        request = await env.request_code(MERCHANT, mobile)
        if request.status_code == 202:
            await env.execute(
                OtpChallenge.__table__.update()
                .where(OtpChallenge.id == request.json()["request_id"])
                .values(resend_available_at=datetime.now(UTC) - timedelta(seconds=1))
            )

    before = len(env.provider.sent)
    limited = await env.request_code(MERCHANT, mobile)
    assert limited.status_code == 429, limited.text
    assert len(env.provider.sent) == before


# --- delivery failure -------------------------------------------------------------------------


async def test_a_delivery_failure_returns_the_existing_error_and_leaks_nothing(env):
    mobile = await merchant_staff(env)
    env.provider.fail_with = OTPDeliveryError("HANUOTP_REJECTED")

    response = await env.request_code(MERCHANT, mobile)
    assert (response.status_code, code_of(response)) == (503, "OTP_DELIVERY_FAILED")
    assert response.headers.get("retry-after") == "30"
    # The failure reason is an internal code; the body must not carry it or the OTP.
    assert "HANUOTP" not in response.text
    assert "otp" not in response.json()["detail"]


async def test_a_failed_delivery_is_not_reported_as_accepted(env):
    mobile = await delivery_rider(env)
    env.provider.fail_with = OTPDeliveryError("HANUOTP_TIMEOUT", retryable=True)

    response = await env.request_code(DELIVERY, mobile)
    assert response.status_code == 503
    detail = response.json()["detail"]
    # The envelope's `request_id` is a correlation id, always present. What must be absent is
    # anything the caller could verify against: a challenge id, an expiry, or the code.
    assert set(detail) == {"code", "message", "fields", "request_id"}
    assert detail["code"] == "OTP_DELIVERY_FAILED"
    assert "expires" not in response.text


async def test_a_failed_delivery_leaves_no_usable_challenge(env):
    """The challenge is rolled back, so a failed send cannot be verified against later."""
    mobile = await merchant_staff(env)
    env.provider.fail_with = OTPDeliveryError("HANUOTP_REJECTED")
    assert (await env.request_code(MERCHANT, mobile)).status_code == 503

    pending = await env.scalar(
        select(OtpChallenge).where(OtpChallenge.mobile_number == mobile, OtpChallenge.consumed_at.is_(None))
    )
    assert pending is None


async def test_delivery_recovers_once_the_provider_does(env):
    """A failure must not lock the number out beyond the existing throttle rules."""
    mobile = await merchant_staff(env)
    env.provider.fail_with = OTPDeliveryError("HANUOTP_TIMEOUT", retryable=True)
    assert (await env.request_code(MERCHANT, mobile)).status_code == 503

    env.provider.fail_with = None
    recovered = await env.request_code(MERCHANT, mobile)
    assert recovered.status_code == 202, recovered.text


async def test_a_successful_send_records_the_provider_and_reference(env):
    """`delivery_provider` and `delivery_reference` already exist — no migration was needed."""
    mobile = await merchant_staff(env)
    request = await env.request_code(MERCHANT, mobile)
    assert request.status_code == 202, request.text

    challenge = await env.scalar(select(OtpChallenge).where(OtpChallenge.id == request.json()["request_id"]))
    assert challenge.delivery_status == "SENT"
    assert challenge.delivery_provider == "capture"
    assert challenge.delivery_reference is not None
