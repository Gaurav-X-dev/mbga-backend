"""A rejected customer fixing their registration and sending it back.

Rejection is not the end of the story: the customer is told what was wrong and expected to
correct it. The backend lets them sign in for exactly that reason - so they can read the
reason rather than be turned away - but signing in issues a full access token, while the
registration routes used to accept only the onboarding token the first attempt was made on.
The customer was left holding the one session that could not act on what it had just shown
them: every edit came back 401 and the app signed them straight back out.
"""

import pytest

from tests.integration.authentication.conftest import code_of
from tests.integration.customers.conftest import (
    CUSTOMER,
    MERCHANT,
    REG,
    registered_customer,
    reviewer,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

CUSTOMER_AUTH = "/api/v1/customer/auth"
REASON = "The GST certificate does not match the business name"


async def rejected(env):
    """A submitted customer their merchant has turned down. Returns a fresh login token."""
    staff_token, merchant, _user = await reviewer(env)
    mobile, _onboarding_token, customer_id = await registered_customer(env, merchant)

    response = await env.post(
        f"{MERCHANT}/customers/{customer_id}/reject", staff_token, json={"reason": REASON}
    )
    assert response.status_code == 200, response.text

    # What the app does next: the session is gone, the customer signs in again.
    login = await env.sign_in(CUSTOMER_AUTH, mobile)
    return login["token"]["access_token"], customer_id


async def test_a_rejected_customer_is_told_why(env):
    token, _customer_id = await rejected(env)

    status_response = await env.get(f"{REG}/status", token)

    assert status_response.status_code == 200, status_response.text
    body = status_response.json()
    assert body["status"] == "REJECTED"
    assert body["rejection_reason"] == REASON


async def test_the_session_that_shows_the_rejection_can_also_fix_it(env):
    """The bug: a 401 here signed the customer out of the screen telling them to try again."""
    token, _customer_id = await rejected(env)

    updated = await env.patch(f"{REG}/profile", token, json={"name": "Corrected Trading Co"})

    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Corrected Trading Co"


async def test_a_corrected_registration_goes_back_for_review(env):
    token, _customer_id = await rejected(env)
    await env.patch(f"{REG}/profile", token, json={"name": "Corrected Trading Co"})

    resubmitted = await env.post(f"{REG}/submit", token)

    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "UNDER_REVIEW"


async def test_an_approved_customer_still_cannot_edit_their_registration(env):
    """The status check, not the token type, is what holds the door - so it must still hold."""
    staff_token, merchant, _user = await reviewer(env)
    mobile, _onboarding_token, customer_id = await registered_customer(env, merchant)
    approved = await env.post(f"{MERCHANT}/customers/{customer_id}/approve", staff_token, json={})
    assert approved.status_code == 200, approved.text
    login = await env.sign_in(CUSTOMER_AUTH, mobile)

    response = await env.patch(
        f"{REG}/profile", login["token"]["access_token"], json={"name": "Sneaky Rename"}
    )

    assert response.status_code == 409
    assert code_of(response) == "REGISTRATION_NOT_EDITABLE"
