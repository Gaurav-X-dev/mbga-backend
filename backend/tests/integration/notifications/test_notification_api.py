"""The in-app notification list (spec §15).

The access model is the thing worth pinning: a customer sees their own bucket, staff share
the merchant's, and read state is per person so one staff member opening a notification does
not hide it from the rest of the team.
"""

import pytest

from tests.integration.notifications.conftest import (
    CUSTOMER,
    MERCHANT,
    code_of,
    customer,
    minutes_ago,
    post,
    queue,
    staff,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


# --- List (§15.1) --------------------------------------------------------------------------


async def test_staff_see_their_merchants_notifications_newest_first(env):
    token, merchant, _user = await staff(env)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id,
                title="Older", created_at=minutes_ago(30))
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="Newer")

    response = await env.get(MERCHANT, token)

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["title"] for row in rows] == ["Newer", "Older"]


async def test_a_notification_carries_everything_the_row_renders(env):
    token, merchant, _user = await staff(env)
    order_id = "ord-123"
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id,
                event_type="ORDER_RECEIVED", entity_type="order", entity_id=order_id,
                title="New order received", body="Order ORD-2609-0001 needs confirming.",
                severity="WARNING")

    row = (await env.get(MERCHANT, token)).json()[0]

    assert row["title"] == "New order received"
    # The outbox column is `body`; the app's contract calls it `message` (spec §3.18).
    assert row["message"] == "Order ORD-2609-0001 needs confirming."
    assert row["severity"] == "WARNING"
    assert row["category"] == "ORDER"
    assert row["read"] is False
    assert row["createdAt"].endswith("Z")
    # The deep link, so the app routes without parsing the title.
    assert row["referenceType"] == "ORDER"
    assert row["referenceId"] == order_id


async def test_a_kyc_event_reads_as_kyc_for_staff_and_account_for_the_customer(env):
    """The same entity means different things to the two audiences."""
    staff_token, merchant, _user = await staff(env)
    customer_token, profile, _u = await customer(env, merchant)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id,
                event_type="kyc.application_submitted", entity_type="kyc_application",
                title="New KYC application")
    await queue(env, recipient_kind="customer", recipient_id=profile.id,
                event_type="customer.approved", entity_type="kyc_application",
                title="Account approved")

    staff_row = (await env.get(MERCHANT, staff_token)).json()[0]
    customer_row = (await env.get(CUSTOMER, customer_token)).json()[0]

    assert staff_row["category"] == "KYC"
    assert customer_row["category"] == "ACCOUNT"


async def test_an_unmapped_event_still_delivers_as_system(env):
    """A lookup miss must not swallow a real message."""
    token, merchant, _user = await staff(env)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id,
                event_type="SOMETHING_NEW", entity_type="widget", title="Heads up")

    row = (await env.get(MERCHANT, token)).json()[0]

    assert row["category"] == "SYSTEM"
    assert row["referenceType"] is None


async def test_a_customer_sees_only_their_own_bucket(env):
    staff_token, merchant, _user = await staff(env)
    customer_token, profile, _u = await customer(env, merchant)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="Staff only")
    await queue(env, recipient_kind="customer", recipient_id=profile.id, title="Mine")

    rows = (await env.get(CUSTOMER, customer_token)).json()

    assert [row["title"] for row in rows] == ["Mine"]
    assert staff_token


async def test_one_customer_cannot_see_anothers(env):
    _staff_token, merchant, _user = await staff(env)
    mine_token, _mine, _u1 = await customer(env, merchant)
    _their_token, theirs, _u2 = await customer(env, merchant)
    await queue(env, recipient_kind="customer", recipient_id=theirs.id, title="Not yours")

    rows = (await env.get(CUSTOMER, mine_token)).json()

    assert rows == []


async def test_staff_do_not_see_another_merchants_notifications(env):
    ours, _our_merchant, _u = await staff(env)
    _theirs, their_merchant, _u2 = await staff(env)
    await queue(env, recipient_kind="merchant", recipient_id=their_merchant.id, title="Theirs")

    rows = (await env.get(MERCHANT, ours)).json()

    assert rows == []


async def test_a_personally_addressed_notification_reaches_that_user(env):
    token, _merchant, user = await staff(env)
    await queue(env, recipient_kind="user", recipient_id=user.id, title="Just for you")

    rows = (await env.get(MERCHANT, token)).json()

    assert [row["title"] for row in rows] == ["Just for you"]


async def test_unread_only_filters_the_list(env):
    token, merchant, _user = await staff(env)
    read_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="Read one")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="Unread one")
    await post(env, f"{MERCHANT}/{read_id}/read", token)

    rows = (await env.get(f"{MERCHANT}?unreadOnly=true", token)).json()

    assert [row["title"] for row in rows] == ["Unread one"]


# --- Detail (§15.2) ------------------------------------------------------------------------


async def test_a_notification_reads_back_by_id(env):
    token, merchant, _user = await staff(env)
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    response = await env.get(f"{MERCHANT}/{notification_id}", token)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == notification_id


async def test_another_merchants_notification_is_not_found_rather_than_forbidden(env):
    ours, _our_merchant, _u = await staff(env)
    _theirs, their_merchant, _u2 = await staff(env)
    theirs = await queue(env, recipient_kind="merchant", recipient_id=their_merchant.id)

    response = await env.get(f"{MERCHANT}/{theirs}", ours)

    assert response.status_code == 404
    assert code_of(response) == "NOTIFICATION_NOT_FOUND"


# --- Read state (§15.3, §15.4) ---------------------------------------------------------------


async def test_marking_read_is_per_user_not_per_bucket(env):
    """A manager opening a notification must not hide it from the accountant."""
    manager_token, merchant, _user = await staff(env)
    colleague_token, _same_merchant, _u2 = await staff(env, merchant)
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    marked = await post(env, f"{MERCHANT}/{notification_id}/read", manager_token)

    assert marked.status_code == 204
    assert (await env.get(MERCHANT, manager_token)).json()[0]["read"] is True
    # The colleague shares the bucket but not the read flag.
    assert (await env.get(MERCHANT, colleague_token)).json()[0]["read"] is False


async def test_marking_read_twice_is_not_an_error(env):
    token, merchant, _user = await staff(env)
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    first = await post(env, f"{MERCHANT}/{notification_id}/read", token)
    second = await post(env, f"{MERCHANT}/{notification_id}/read", token)

    assert first.status_code == second.status_code == 204


async def test_marking_someone_elses_read_is_not_found(env):
    ours, _our_merchant, _u = await staff(env)
    _theirs, their_merchant, _u2 = await staff(env)
    theirs = await queue(env, recipient_kind="merchant", recipient_id=their_merchant.id)

    response = await post(env, f"{MERCHANT}/{theirs}/read", ours)

    assert response.status_code == 404


async def test_read_all_clears_the_badge(env):
    token, merchant, _user = await staff(env)
    for index in range(3):
        await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title=f"N{index}")

    before = (await env.get(f"{MERCHANT}/unread-count", token)).json()
    cleared = await post(env, f"{MERCHANT}/read-all", token)
    after = (await env.get(f"{MERCHANT}/unread-count", token)).json()

    assert before["unread"] == 3
    assert cleared.status_code == 204
    assert after["unread"] == 0


async def test_read_all_does_not_touch_another_users_badge(env):
    manager_token, merchant, _user = await staff(env)
    colleague_token, _same, _u2 = await staff(env, merchant)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    await post(env, f"{MERCHANT}/read-all", manager_token)

    assert (await env.get(f"{MERCHANT}/unread-count", colleague_token)).json()["unread"] == 1


async def test_read_all_on_an_empty_bucket_is_harmless(env):
    token, _merchant, _user = await staff(env)

    response = await post(env, f"{MERCHANT}/read-all", token)

    assert response.status_code == 204


async def test_the_badge_counts_only_this_actors_bucket(env):
    ours, _our_merchant, _u = await staff(env)
    _theirs, their_merchant, _u2 = await staff(env)
    await queue(env, recipient_kind="merchant", recipient_id=their_merchant.id)

    assert (await env.get(f"{MERCHANT}/unread-count", ours)).json()["unread"] == 0


# --- Auth ------------------------------------------------------------------------------------


async def test_notifications_need_a_session(env):
    assert (await env.get(MERCHANT)).status_code == 401


async def test_a_merchant_token_cannot_use_the_customer_route(env):
    token, _merchant, _user = await staff(env)

    response = await env.get(CUSTOMER, token)

    assert response.status_code == 403
    assert code_of(response) == "CHANNEL_NOT_ALLOWED"


async def test_no_permission_is_required_to_read_your_own_notifications(env):
    """Spec §2.1: a customer holds no permissions; ownership is the rule."""
    _staff_token, merchant, _user = await staff(env)
    token, profile, _u = await customer(env, merchant)
    await queue(env, recipient_kind="customer", recipient_id=profile.id)

    assert (await env.get(CUSTOMER, token)).status_code == 200
