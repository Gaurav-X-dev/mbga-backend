"""Merchant-created customers, listing, detail and order eligibility."""

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from tests.integration.authentication.conftest import code_of, random_mobile
from tests.integration.customers.conftest import (
    CUSTOMER,
    MERCHANT,
    registration_body,
    reviewer,
    site,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def create_customer(env, token, *, customer_type="RETAIL", mobile=None, **overrides):
    mobile = mobile or random_mobile()
    body = await registration_body(env, MERCHANT, token, customer_type=customer_type, mobile=mobile.removeprefix("+91"))
    if customer_type == "INDUSTRIAL":
        body["sites"] = [site()]
    body.update(overrides)
    return mobile, await env.post(f"{MERCHANT}/customers", token, json=body)


async def test_staff_can_add_a_retail_customer(env):
    token, _merchant, _staff = await reviewer(env)
    mobile, response = await create_customer(env, token)
    assert response.status_code == 201, response.text

    customer = response.json()
    assert customer["accountStatus"] == "PENDING"
    assert customer["kycStatus"] == "PENDING"
    assert customer["pricingTier"] == "STANDARD"
    assert customer["code"].startswith("MBGA-R-")
    assert customer["mobile"] == mobile.removeprefix("+91")
    assert customer["sites"] == []
    assert customer["runningBalance"] == 0
    # Spec 3.4: only masked identifiers ever leave the backend.
    assert {document["numberMasked"] for document in customer["documents"]} == {"XXXX XXXX 1234", "XXXXX1234F"}
    assert "123412341234" not in response.text
    assert "ABCDE1234F" not in response.text


async def test_staff_can_add_an_industrial_customer_with_sites(env):
    token, _, _ = await reviewer(env)
    _, response = await create_customer(env, token, customer_type="INDUSTRIAL")
    assert response.status_code == 201, response.text

    customer = response.json()
    assert customer["code"].startswith("MBGA-I-")
    assert customer["gstin"] == "23AAACA1234F1Z5"
    assert len(customer["sites"]) == 1
    assert customer["sites"][0]["isPrimary"] is True
    masked = {document["type"]: document["numberMasked"] for document in customer["documents"]}
    assert masked == {"FSSAI": "XXXXXXXXXX1234", "GST": "23XXXXXXXXXX1Z5"}
    assert "12345678901234" not in response.text


async def test_the_customer_can_sign_in_and_see_verification_pending(env):
    """Spec 7.1: a staff-created customer signs in immediately and sees Verification Pending.

    This used to be refused with `403 ACCOUNT_PENDING_APPROVAL`. That gate was removed on
    22 Sep 2026 so the app can route on `next_action` instead of turning the customer away
    with an error they cannot act on.
    """
    token, _, _ = await reviewer(env)
    mobile, response = await create_customer(env, token)
    assert response.status_code == 201, response.text

    login = await env.sign_in(f"{CUSTOMER}/auth", mobile)
    assert login["next_action"] == "WAIT_FOR_APPROVAL"
    assert login["customer_profile"]["status"] == "UNDER_REVIEW"

    profile = await env.get(f"{CUSTOMER}/profile", login["token"]["access_token"])
    assert profile.status_code == 200, profile.text
    assert profile.json()["accountStatus"] == "PENDING"


async def test_a_staff_mobile_number_cannot_become_a_customer(env):
    token, _, staff = await reviewer(env)
    _, response = await create_customer(env, token, mobile=staff.mobile_number)
    assert response.status_code == 422, response.text
    reported = {item["field"]: item["code"] for item in response.json()["detail"]["fields"]}
    assert reported["mobile"] == "staff_number"


async def test_a_duplicate_customer_mobile_is_refused(env):
    token, _, _ = await reviewer(env)
    mobile, first = await create_customer(env, token)
    assert first.status_code == 201, first.text

    _, second = await create_customer(env, token, mobile=mobile)
    assert (second.status_code, code_of(second)) == (409, "REGISTRATION_PROFILE_EXISTS")


async def test_ownership_fields_in_the_body_are_ignored(env):
    """Merchant, code, tier, status and review fields come from the session, never the body."""
    token, merchant, _ = await reviewer(env)
    _, other_merchant, _ = await reviewer(env)
    _, response = await create_customer(
        env,
        token,
        merchantId=other_merchant.id,
        code="MBGA-R-9999",
        pricingTier="KEY_ACCOUNT",
        accountStatus="APPROVED",
        kycStatus="VERIFIED",
        runningBalance=500000,
    )
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer["code"] != "MBGA-R-9999"
    assert customer["pricingTier"] == "STANDARD"
    assert customer["accountStatus"] == "PENDING"
    assert customer["runningBalance"] == 0

    stored = await env.scalar(select(CustomerProfile).where(CustomerProfile.id == customer["id"]))
    assert stored.merchant_id == merchant.id


async def test_a_created_customer_gets_no_staff_role(env):
    token, _, _ = await reviewer(env)
    mobile, response = await create_customer(env, token)
    assert response.status_code == 201, response.text

    user = await env.scalar(select(User).where(User.mobile_number == mobile))
    assert user.role == "customer"
    assert user.status == "PENDING"
    # No role is granted at all before approval.
    assert await env.scalar(select(UserRole).where(UserRole.user_id == user.id)) is None


async def test_creating_a_customer_needs_the_create_permission(env):
    token, _, _ = await reviewer(env, permissions=("customers.view",))
    _, response = await create_customer(env, token)
    assert (response.status_code, code_of(response)) == (403, "PERMISSION_DENIED")


async def test_a_failed_create_leaves_nothing_behind(env):
    """The user, profile, documents, sites and application all roll back together."""
    token, _, _ = await reviewer(env)
    mobile = random_mobile()
    body = await registration_body(env, MERCHANT, token, customer_type="INDUSTRIAL", mobile=mobile.removeprefix("+91"))
    body["sites"] = []  # invalid: an industrial customer needs a site

    response = await env.post(f"{MERCHANT}/customers", token, json=body)
    assert response.status_code == 422, response.text
    assert await env.scalar(select(User).where(User.mobile_number == mobile)) is None
    assert await env.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile)) is None


async def test_the_list_is_scoped_searched_and_filtered(env):
    token, _merchant, _ = await reviewer(env)
    other_token, _, _ = await reviewer(env)
    _, mine = await create_customer(env, token)
    _, theirs = await create_customer(env, other_token)
    assert mine.status_code == theirs.status_code == 201

    listed = await env.get(f"{MERCHANT}/customers", token)
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["items"]}
    assert mine.json()["id"] in ids
    assert theirs.json()["id"] not in ids

    by_name = await env.get(f"{MERCHANT}/customers?search=Test%20Bakery", token)
    assert mine.json()["id"] in {item["id"] for item in by_name.json()["items"]}
    by_code = await env.get(f"{MERCHANT}/customers?search={mine.json()['code']}", token)
    assert [item["id"] for item in by_code.json()["items"]] == [mine.json()["id"]]

    pending = await env.get(f"{MERCHANT}/customers?accountStatus=PENDING", token)
    assert mine.json()["id"] in {item["id"] for item in pending.json()["items"]}
    approved = await env.get(f"{MERCHANT}/customers?accountStatus=APPROVED", token)
    assert mine.json()["id"] not in {item["id"] for item in approved.json()["items"]}

    retail = await env.get(f"{MERCHANT}/customers?customerType=RETAIL", token)
    assert mine.json()["id"] in {item["id"] for item in retail.json()["items"]}
    industrial = await env.get(f"{MERCHANT}/customers?customerType=INDUSTRIAL", token)
    assert mine.json()["id"] not in {item["id"] for item in industrial.json()["items"]}


async def test_an_unknown_filter_value_is_a_validation_error(env):
    token, _, _ = await reviewer(env)
    response = await env.get(f"{MERCHANT}/customers?accountStatus=NOPE", token)
    assert (response.status_code, code_of(response)) == (422, "VALIDATION_ERROR")


async def test_detail_is_merchant_scoped(env):
    token, _, _ = await reviewer(env)
    other_token, _, _ = await reviewer(env)
    _, created = await create_customer(env, token)
    customer_id = created.json()["id"]

    own = await env.get(f"{MERCHANT}/customers/{customer_id}", token)
    assert own.status_code == 200, own.text
    assert own.json()["id"] == customer_id

    foreign = await env.get(f"{MERCHANT}/customers/{customer_id}", other_token)
    assert (foreign.status_code, code_of(foreign)) == (404, "CUSTOMER_NOT_FOUND")


async def test_eligibility_lists_every_blocking_reason(env):
    token, _merchant, _ = await reviewer(env)
    _, created = await create_customer(env, token)
    customer_id = created.json()["id"]

    response = await env.get(f"{MERCHANT}/customers/{customer_id}/eligibility", token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eligible"] is False
    # Both problems are reported, not just the first one the policy hits.
    assert len(body["reasons"]) == 2
    assert any("approved customers" in reason for reason in body["reasons"])
    assert any("KYC" in reason for reason in body["reasons"])


async def test_an_approved_verified_customer_is_eligible(env):
    token, _merchant, _ = await reviewer(env)
    _, created = await create_customer(env, token)
    customer_id = created.json()["id"]
    approved = await env.post(f"{MERCHANT}/customers/{customer_id}/approve", token)
    assert approved.status_code == 200, approved.text

    response = await env.get(f"{MERCHANT}/customers/{customer_id}/eligibility", token)
    assert response.json() == {"eligible": True, "reasons": []}


async def test_eligibility_needs_the_order_create_permission(env):
    full_token, merchant, _ = await reviewer(env)
    _, created = await create_customer(env, full_token)
    limited, _, _ = await reviewer(env, merchant, permissions=("customers.view",))

    response = await env.get(f"{MERCHANT}/customers/{created.json()['id']}/eligibility", limited)
    assert (response.status_code, code_of(response)) == (403, "PERMISSION_DENIED")
