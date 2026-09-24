"""Which customer states may sign in, now that pending no longer blocks.

Kept out of the authentication package on purpose: these assert the *new* product contract
agreed on 22 Sep 2026, so they must not be mistaken for the frozen 212-test baseline.
"""

import pytest
from sqlalchemy import select, update

from app.modules.customers.models import CustomerProfile
from tests.integration.authentication.conftest import code_of, random_mobile
from tests.integration.sms.conftest import CUSTOMER, MERCHANT, REGISTRATION

CUSTOMER_API = "/api/v1/customer"

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def _registered_customer(env):
    """A customer sitting at UNDER_REVIEW, created through the shipped onboarding routes."""
    role = f"rev_{random_mobile()[-6:]}"
    await env.create_role(role, "MERCHANT", ["customers.view", "customers.approve"])
    staff, merchant = await env.create_merchant_staff(roles=("manager", role))
    reviewer = (await env.sign_in(MERCHANT, staff.mobile_number))["token"]["access_token"]

    mobile = random_mobile()
    token = (await env.sign_in(REGISTRATION, mobile))["token"]["access_token"]
    created = await env.post(
        f"{REGISTRATION}/profile",
        token,
        json={"merchant_code": merchant.code, "customer_type": "retail", "name": "Sharma Stores"},
    )
    assert created.status_code == 201, created.text
    assert (await env.post(f"{REGISTRATION}/submit", token)).status_code == 200
    return mobile, created.json()["id"], reviewer


async def test_a_customer_awaiting_review_signs_in_and_is_sent_to_the_status_screen(env):
    mobile, _, _ = await _registered_customer(env)

    login = await env.sign_in(CUSTOMER, mobile)
    assert login["next_action"] == "WAIT_FOR_APPROVAL"
    assert login["customer_profile"]["status"] == "UNDER_REVIEW"
    # A real session, not a restricted one: the app can call customer routes with it.
    assert login["session_type"] == "access"


async def test_the_signed_in_pending_customer_can_read_their_own_profile(env):
    """The status screen needs this call; blocking it would defeat the whole change."""
    mobile, customer_id, _ = await _registered_customer(env)
    login = await env.sign_in(CUSTOMER, mobile)

    profile = await env.get(f"{CUSTOMER_API}/profile", login["token"]["access_token"])
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == customer_id
    assert profile.json()["accountStatus"] == "PENDING"


async def test_approval_moves_the_same_customer_to_the_home_screen(env):
    """The routing flips on the stored status, whichever route set it.

    The status is set directly here rather than through the approve endpoint: approval has
    its own tests, and going through it would drag this one into document and scan rules that
    have nothing to do with sign-in routing.
    """
    mobile, customer_id, _ = await _registered_customer(env)
    assert (await env.sign_in(CUSTOMER, mobile))["next_action"] == "WAIT_FOR_APPROVAL"

    await env.execute(
        update(CustomerProfile).where(CustomerProfile.id == customer_id).values(status="APPROVED")
    )
    from sqlalchemy import update as sql_update

    from app.modules.users.models import User

    await env.execute(sql_update(User).where(User.mobile_number == mobile).values(status="ACTIVE"))
    await env.assign_role((await env.scalar(select(User.id).where(User.mobile_number == mobile))), "customer")

    after = await env.sign_in(CUSTOMER, mobile)
    assert after["next_action"] == "OPEN_CUSTOMER_HOME"
    assert after["customer_profile"]["status"] == "APPROVED"


async def test_a_suspended_customer_is_still_refused(env):
    """Suspension is an administrative decision; its screen is contact support, not wait."""
    mobile, customer_id, _ = await _registered_customer(env)
    await env.execute(
        update(CustomerProfile).where(CustomerProfile.id == customer_id).values(status="SUSPENDED")
    )

    refused = await env.request_code(CUSTOMER, mobile)
    assert (refused.status_code, code_of(refused)) == (403, "ACCOUNT_SUSPENDED")


async def test_a_blocked_customer_is_still_refused(env):
    from app.modules.users.models import User

    mobile, _, _ = await _registered_customer(env)
    await env.execute(update(User).where(User.mobile_number == mobile).values(status="BLOCKED"))
    refused = await env.request_code(CUSTOMER, mobile)
    assert (refused.status_code, code_of(refused)) == (403, "ACCOUNT_BLOCKED")


async def test_someone_who_never_registered_still_cannot_use_the_customer_app(env):
    """Relaxing the gate must not let a staff-only account into the Customer app."""
    staff, _ = await env.create_merchant_staff()
    refused = await env.request_code(CUSTOMER, staff.mobile_number)
    assert refused.status_code == 403, refused.text
