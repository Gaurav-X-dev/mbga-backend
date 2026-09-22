"""Merchant KYC review: the queue, application detail and the approve/reject decision."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.authentication.account_state import CUSTOMER_UNDER_REVIEW
from app.modules.customers.constants import ApplicationStatus, KycStatus
from app.modules.customers.models import CustomerProfile, KycApplication
from app.shared.notifications.models import NotificationOutbox
from tests.integration.authentication.conftest import code_of, random_mobile
from tests.integration.customers.conftest import (
    MERCHANT,
    REG,
    registered_customer,
    registration_body,
    reviewer,
    site,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def staff_customer(env, token, *, customer_type="RETAIL"):
    mobile = random_mobile()
    body = await registration_body(env, MERCHANT, token, customer_type=customer_type, mobile=mobile.removeprefix("+91"))
    if customer_type == "INDUSTRIAL":
        body["sites"] = [site()]
    response = await env.post(f"{MERCHANT}/customers", token, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def application_of(env, token, customer_id: str, *, status: str = "ALL") -> dict:
    listed = await env.get(f"{MERCHANT}/kyc/applications?status={status}", token)
    assert listed.status_code == 200, listed.text
    return next(item for item in listed.json()["items"] if item["customerId"] == customer_id)


async def test_the_queue_defaults_to_pending_and_is_merchant_scoped(env):
    token, _merchant, _ = await reviewer(env)
    other_token, _, _ = await reviewer(env)
    mine = await staff_customer(env, token)
    theirs = await staff_customer(env, other_token)

    listed = await env.get(f"{MERCHANT}/kyc/applications", token)
    assert listed.status_code == 200, listed.text
    customer_ids = {item["customerId"] for item in listed.json()["items"]}
    assert mine["id"] in customer_ids
    assert theirs["id"] not in customer_ids
    assert {item["status"] for item in listed.json()["items"]} == {"PENDING"}


async def test_the_queue_can_be_filtered_by_decision(env):
    token, _, _ = await reviewer(env)
    approved_customer = await staff_customer(env, token)
    rejected_customer = await staff_customer(env, token)
    assert (await env.post(f"{MERCHANT}/customers/{approved_customer['id']}/approve", token)).status_code == 200
    rejected = await env.post(
        f"{MERCHANT}/customers/{rejected_customer['id']}/reject",
        token,
        json={"reason": "The PAN card image is unreadable"},
    )
    assert rejected.status_code == 200, rejected.text

    for value, expected in [("APPROVED", approved_customer), ("REJECTED", rejected_customer)]:
        listed = await env.get(f"{MERCHANT}/kyc/applications?status={value}", token)
        assert expected["id"] in {item["customerId"] for item in listed.json()["items"]}
        assert {item["status"] for item in listed.json()["items"]} == {value}

    everything = await env.get(f"{MERCHANT}/kyc/applications?status=ALL", token)
    assert {approved_customer["id"], rejected_customer["id"]} <= {item["customerId"] for item in everything.json()["items"]}

    invalid = await env.get(f"{MERCHANT}/kyc/applications?status=MAYBE", token)
    assert (invalid.status_code, code_of(invalid)) == (422, "VALIDATION_ERROR")


async def test_the_queue_is_newest_first(env):
    """Spec 8.1 orders the queue by submittedAt descending.

    Asserted on the returned timestamps rather than on insertion order, because MySQL
    DATETIME columns here store whole seconds: two applications created in the same second
    carry the same `submittedAt` and their relative order is genuinely undefined. The
    ordering contract is still fully checked - it is the tie that is not.
    """
    token, _, _ = await reviewer(env)
    first = await staff_customer(env, token)
    second = await staff_customer(env, token)

    listed = await env.get(f"{MERCHANT}/kyc/applications", token)
    items = listed.json()["items"]
    assert {first["id"], second["id"]} <= {item["customerId"] for item in items}
    submitted = [item["submittedAt"] for item in items]
    assert submitted == sorted(submitted, reverse=True)


async def test_application_detail_returns_masked_documents_and_sites(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token, customer_type="INDUSTRIAL")
    application = await application_of(env, token, customer["id"])

    response = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customerId"] == customer["id"]
    assert body["status"] == "PENDING"
    assert body["deliveryAddress"]["pincode"] == "452001"
    assert len(body["sites"]) == 1
    assert {document["numberMasked"] for document in body["documents"]} == {"XXXXXXXXXX1234", "23XXXXXXXXXX1Z5"}
    # No full identifier and no storage path anywhere in the payload.
    assert "12345678901234" not in response.text
    assert "kyc/" not in response.text


async def test_application_detail_is_merchant_scoped(env):
    token, _, _ = await reviewer(env)
    other_token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)
    application = await application_of(env, token, customer["id"])

    foreign = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", other_token)
    assert (foreign.status_code, code_of(foreign)) == (404, "APPLICATION_NOT_FOUND")
    missing = await env.get(f"{MERCHANT}/kyc/applications/does-not-exist", token)
    assert (missing.status_code, code_of(missing)) == (404, "APPLICATION_NOT_FOUND")


async def test_the_review_permissions_are_both_required(env):
    full_token, merchant, _ = await reviewer(env)
    customer = await staff_customer(env, full_token)
    application = await application_of(env, full_token, customer["id"])

    no_review, _, _ = await reviewer(env, merchant, permissions=("customers.view",))
    assert (await env.get(f"{MERCHANT}/kyc/applications", no_review)).status_code == 403

    queue_only, _, _ = await reviewer(env, merchant, permissions=("customers.view", "customers.review"))
    assert (await env.get(f"{MERCHANT}/kyc/applications", queue_only)).status_code == 200
    # The queue is visible, but the documents on the detail screen are not.
    detail = await env.get(f"{MERCHANT}/kyc/applications/{application['id']}", queue_only)
    assert (detail.status_code, code_of(detail)) == (403, "PERMISSION_DENIED")


async def test_approval_updates_the_customer_the_documents_and_the_application(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    approved = await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)
    assert approved.status_code == 200, approved.text

    detail = await env.get(f"{MERCHANT}/customers/{customer['id']}", token)
    body = detail.json()
    assert body["accountStatus"] == "APPROVED"
    assert body["kycStatus"] == "VERIFIED"
    assert body["approvedAt"] is not None
    assert {document["status"] for document in body["documents"]} == {"VERIFIED"}

    application = await application_of(env, token, customer["id"])
    assert application["status"] == "APPROVED"
    assert application["reviewedAt"] is not None
    assert application["reviewedBy"]  # the reviewer's name, taken from the token


async def legacy_incomplete_profile(env, merchant, *, customer_type: str) -> str:
    now = datetime.now(UTC)
    user = await env.create_user(status="PENDING", roles=(), name="Legacy Customer")
    customer_id = str(uuid4())
    await env.execute(
        CustomerProfile.__table__.insert().values(
            id=customer_id,
            user_id=user.id,
            merchant_id=merchant.id,
            merchant_code=merchant.code,
            customer_type=customer_type,
            mobile_number=user.mobile_number,
            name="Legacy Business",
            owner_name=None,
            status=CUSTOMER_UNDER_REVIEW,
            kyc_status=KycStatus.PENDING.value,
            mobile_verified_at=now,
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await env.execute(
        KycApplication.__table__.insert().values(
            id=str(uuid4()),
            customer_id=customer_id,
            merchant_id=merchant.id,
            status=ApplicationStatus.PENDING.value,
            submitted_at=now,
            submitted_by_user_id=user.id,
            created_at=now,
            updated_at=now,
        )
    )
    return customer_id


@pytest.mark.parametrize("customer_type", ["RETAIL", "INDUSTRIAL"])
async def test_incomplete_legacy_customers_are_not_approved(env, customer_type):
    token, merchant, _ = await reviewer(env)
    customer_id = await legacy_incomplete_profile(env, merchant, customer_type=customer_type)

    response = await env.post(f"{MERCHANT}/customers/{customer_id}/approve", token)

    assert (response.status_code, code_of(response)) == (409, "REGISTRATION_INCOMPLETE")


@pytest.mark.parametrize("settings_overrides", [{"allow_skipped_kyc_scan_in_local": False}], indirect=True)
async def test_skipped_scan_is_rejected_without_explicit_local_allowance(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    response = await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)

    assert (response.status_code, code_of(response)) == (409, "DOCUMENT_SCAN_PENDING")


async def test_an_approved_customer_can_sign_in(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)
    mobile = f"+91{customer['mobile']}"
    assert (await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)).status_code == 200

    login = await env.sign_in("/api/v1/customer/auth", mobile)
    assert login["next_action"] == "OPEN_CUSTOMER_HOME"
    profile = await env.get("/api/v1/customer/profile", login["token"]["access_token"])
    assert profile.status_code == 200, profile.text
    assert profile.json()["accountStatus"] == "APPROVED"


async def test_rejection_requires_a_substantial_reason(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    empty = await env.post(f"{MERCHANT}/customers/{customer['id']}/reject", token, json={})
    assert empty.status_code == 422, empty.text
    short = await env.post(f"{MERCHANT}/customers/{customer['id']}/reject", token, json={"reason": "no"})
    assert short.status_code == 422, short.text

    rejected = await env.post(
        f"{MERCHANT}/customers/{customer['id']}/reject",
        token,
        json={"reason": "The GST certificate does not match the business name"},
    )
    assert rejected.status_code == 200, rejected.text
    detail = (await env.get(f"{MERCHANT}/customers/{customer['id']}", token)).json()
    assert detail["accountStatus"] == "REJECTED"
    assert detail["kycStatus"] == "REJECTED"
    assert detail["rejectionReason"] == "The GST certificate does not match the business name"


async def test_a_decision_cannot_be_taken_twice(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    assert (await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)).status_code == 200
    again = await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)
    assert (again.status_code, code_of(again)) == (409, "INVALID_STATUS_TRANSITION")
    reversed_decision = await env.post(
        f"{MERCHANT}/customers/{customer['id']}/reject", token, json={"reason": "Changed my mind about this"}
    )
    assert (reversed_decision.status_code, code_of(reversed_decision)) == (409, "INVALID_STATUS_TRANSITION")


async def test_concurrent_approve_and_reject_cannot_both_win(env):
    """The row lock means exactly one decision is recorded, whichever arrives first."""
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    approve, reject = await asyncio.gather(
        env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token),
        env.post(f"{MERCHANT}/customers/{customer['id']}/reject", token, json={"reason": "Documents are not readable"}),
    )
    outcomes = sorted([approve.status_code, reject.status_code])
    assert outcomes == [200, 409], f"{approve.text} | {reject.text}"

    final = (await env.get(f"{MERCHANT}/customers/{customer['id']}", token)).json()
    assert final["accountStatus"] in {"APPROVED", "REJECTED"}
    # Whichever won, the two statuses agree with each other.
    assert (final["kycStatus"] == "VERIFIED") == (final["accountStatus"] == "APPROVED")


async def test_a_reviewer_cannot_decide_another_merchants_customer(env):
    token, _, _ = await reviewer(env)
    other_token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)

    foreign = await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", other_token)
    assert (foreign.status_code, code_of(foreign)) == (404, "CUSTOMER_NOT_FOUND")


async def test_decisions_queue_the_customer_notification(env):
    token, _, _ = await reviewer(env)
    customer = await staff_customer(env, token)
    assert (await env.post(f"{MERCHANT}/customers/{customer['id']}/approve", token)).status_code == 200

    queued = await env.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.recipient_id == customer["id"],
            NotificationOutbox.event_type == "customer.approved",
        )
    )
    assert queued is not None
    assert queued.title == "Account approved"
    assert queued.delivered_at is None
    # Nothing sensitive is ever written into a notification body.
    assert "123412341234" not in queued.body


async def test_a_self_registered_customer_is_reviewed_the_same_way(env):
    """The self-registration and staff-created paths converge on one review flow."""
    token, merchant, _ = await reviewer(env)
    _, onboarding_token, customer_id = await registered_customer(env, merchant)

    application = await application_of(env, token, customer_id)
    assert application["status"] == "PENDING"
    assert len(application["documents"]) == 2

    assert (await env.post(f"{MERCHANT}/customers/{customer_id}/approve", token)).status_code == 200
    status_response = await env.get(f"{REG}/status", onboarding_token)
    assert status_response.json()["progress"]["accountStatus"] == "APPROVED"
    assert status_response.json()["progress"]["kycStatus"] == "VERIFIED"
