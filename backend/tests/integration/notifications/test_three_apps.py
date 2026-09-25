"""Three apps, three buckets, and nothing leaking between them.

Each app reads what belongs to it and nothing else. The tests are written as the negative
as much as the positive, because a notification screen that shows one row too many is a
data leak, and one that shows one row too few is an order nobody acted on.

Also pinned here: a notification that has already been pushed stays on the list. The push
is how it reaches a phone; the list is how it is read afterwards, and delivering must never
be the thing that removes it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.authentication.models import LoginSession
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.notifications.events import deliveries
from app.shared.notifications.outbox import NotificationOutboxWriter
from tests.integration.notifications.conftest import (
    CUSTOMER,
    MERCHANT,
    code_of,
    customer,
    queue,
    staff,
)
from tests.integration.notifications.test_dispatcher import StubFcm, StubProjects, _dispatch, _row

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

DELIVERY = "/api/v1/delivery/notifications"
DELIVERY_AUTH = "/api/v1/delivery/auth"


async def driver(auth_env, merchant, *, fcm_token: str | None = None):
    """An approved driver of `merchant`, signed in on the delivery app."""
    user, merchant, _profile = await auth_env.create_delivery_user(merchant)
    device = {"device_id": f"dev-{uuid4().hex[:8]}", "device_type": "android", "app_version": "1.0.0"}
    if fcm_token:
        device["fcm_token"] = fcm_token
    request = await auth_env.client.post(
        f"{DELIVERY_AUTH}/otp/request", json={"mobile_number": user.mobile_number, "device": device}
    )
    assert request.status_code == 202, request.text
    verify = await auth_env.client.post(
        f"{DELIVERY_AUTH}/otp/verify",
        json={
            "request_id": request.json()["request_id"],
            "otp": auth_env.last_code(user.mobile_number),
            "device": device,
        },
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["token"]["access_token"], user, merchant


# --- Each app reads its own bucket -------------------------------------------------------


async def test_a_driver_reads_what_is_addressed_to_them(env):
    """The gap this closes: the delivery app had no notification screen at all."""
    _staff_token, merchant, _u = await staff(env)
    token, user, _merchant = await driver(env, merchant)
    await queue(
        env,
        recipient_kind="user",
        recipient_id=user.id,
        event_type="DELIVERY_DISPATCHED",
        entity_type="order",
        title="Delivery assigned",
        body="Order ORD-2609-0001 is ready to load.",
    )

    response = await env.get(DELIVERY, token)

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["title"] for row in rows] == ["Delivery assigned"]
    assert rows[0]["category"] == "ORDER"
    assert rows[0]["read"] is False


async def test_a_driver_does_not_read_the_merchants_bucket(env):
    """A driver is not staff. "New order received" is a job for the office."""
    _staff_token, merchant, _u = await staff(env)
    token, _user, _m = await driver(env, merchant)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="New order received")

    rows = (await env.get(DELIVERY, token)).json()

    assert rows == []


async def test_a_driver_does_not_read_a_customers_bucket(env):
    _staff_token, merchant, _u = await staff(env)
    _customer_token, profile, _cu = await customer(env, merchant)
    token, _user, _m = await driver(env, merchant)
    await queue(env, recipient_kind="customer", recipient_id=profile.id, title="Order placed")

    assert (await env.get(DELIVERY, token)).json() == []


async def test_one_drivers_notification_is_not_another_drivers(env):
    _staff_token, merchant, _u = await staff(env)
    mine_token, mine, _m1 = await driver(env, merchant)
    _their_token, theirs, _m2 = await driver(env, merchant)
    await queue(env, recipient_kind="user", recipient_id=theirs.id, title="Not yours")

    assert (await env.get(DELIVERY, mine_token)).json() == []
    assert mine


async def test_the_three_apps_each_see_exactly_their_own(env):
    """One merchant, one customer, one driver, three notifications, no crossover."""
    staff_token, merchant, _su = await staff(env)
    customer_token, profile, _cu = await customer(env, merchant)
    driver_token, driver_user, _m = await driver(env, merchant)
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id, title="For staff")
    await queue(env, recipient_kind="customer", recipient_id=profile.id, title="For the customer")
    await queue(env, recipient_kind="user", recipient_id=driver_user.id, title="For the driver")

    seen = {
        "merchant": [r["title"] for r in (await env.get(MERCHANT, staff_token)).json()],
        "customer": [r["title"] for r in (await env.get(CUSTOMER, customer_token)).json()],
        "delivery": [r["title"] for r in (await env.get(DELIVERY, driver_token)).json()],
    }

    assert seen == {
        "merchant": ["For staff"],
        "customer": ["For the customer"],
        "delivery": ["For the driver"],
    }


# --- Channel isolation ---------------------------------------------------------------------


async def test_a_delivery_token_cannot_use_the_merchant_route(env):
    _staff_token, merchant, _u = await staff(env)
    token, _user, _m = await driver(env, merchant)

    response = await env.get(MERCHANT, token)

    assert response.status_code == 403
    assert code_of(response) == "CHANNEL_NOT_ALLOWED"


async def test_a_merchant_token_cannot_use_the_delivery_route(env):
    token, _merchant, _u = await staff(env)

    response = await env.get(DELIVERY, token)

    assert response.status_code == 403
    assert code_of(response) == "CHANNEL_NOT_ALLOWED"


async def test_the_delivery_bell_needs_a_session(env):
    assert (await env.get(DELIVERY)).status_code == 401


# --- A driver's own read state ---------------------------------------------------------------


async def test_a_driver_can_mark_read_and_clear_their_badge(env):
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant)
    first = await queue(env, recipient_kind="user", recipient_id=user.id, title="One")
    await queue(env, recipient_kind="user", recipient_id=user.id, title="Two")

    before = (await env.get(f"{DELIVERY}/unread-count", token)).json()
    marked = await env.post(f"{DELIVERY}/{first}/read", token)
    after = (await env.get(f"{DELIVERY}/unread-count", token)).json()
    cleared = await env.post(f"{DELIVERY}/read-all", token)
    finally_ = (await env.get(f"{DELIVERY}/unread-count", token)).json()

    assert before["unread"] == 2
    assert marked.status_code == 204
    assert after["unread"] == 1
    assert cleared.status_code == 204
    assert finally_["unread"] == 0


async def test_a_driver_cannot_mark_someone_elses_read(env):
    _staff_token, merchant, _u = await staff(env)
    mine_token, _mine, _m1 = await driver(env, merchant)
    _their_token, theirs, _m2 = await driver(env, merchant)
    notification_id = await queue(env, recipient_kind="user", recipient_id=theirs.id)

    response = await env.post(f"{DELIVERY}/{notification_id}/read", mine_token)

    assert response.status_code == 404


# --- Pushed, and still on the list -------------------------------------------------------------


async def test_a_pushed_notification_stays_on_the_list(env):
    """Delivering it to a phone is not the same as consuming it.

    The push is how it reaches the device; the list is how it is read afterwards and how it
    is found again next week. Sending must never remove it.
    """
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant, fcm_token="driver-phone")
    notification_id = await queue(
        env, recipient_kind="user", recipient_id=user.id, title="Delivery assigned"
    )
    app = StubFcm(project_id="mbga-delivery-partner")

    await _dispatch(env, StubProjects(by_channel={"DELIVERY": app}))

    assert app.tokens == ["driver-phone"], "sent through the delivery project"
    # This row is stamped as delivered. Asserted on the row rather than on the pass's total,
    # because the dispatcher drains the whole outbox and the suite shares one database.
    assert (await _row(env, notification_id)).delivered_at is not None
    # ...and is still exactly where the driver will look for it.
    rows = (await env.get(DELIVERY, token)).json()
    assert [row["id"] for row in rows] == [notification_id]
    assert rows[0]["read"] is False, "pushed is not read"


async def test_marking_read_does_not_remove_it_either(env):
    """The list is a history, not an inbox that empties."""
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant)
    notification_id = await queue(env, recipient_kind="user", recipient_id=user.id)

    await env.post(f"{DELIVERY}/{notification_id}/read", token)

    rows = (await env.get(DELIVERY, token)).json()
    assert [row["id"] for row in rows] == [notification_id]
    assert rows[0]["read"] is True


async def test_every_delivered_notification_is_still_readable(env):
    """Across all three apps at once: nothing is lost by being sent."""
    staff_token, merchant, _su = await staff(env, fcm_token="staff-phone")
    customer_token, profile, _cu = await customer(env, merchant, fcm_token="customer-phone")
    driver_token, driver_user, _m = await driver(env, merchant, fcm_token="driver-phone")
    queued = [
        await queue(env, recipient_kind="merchant", recipient_id=merchant.id),
        await queue(env, recipient_kind="customer", recipient_id=profile.id),
        await queue(env, recipient_kind="user", recipient_id=driver_user.id),
    ]

    await _dispatch(env, StubProjects())

    # These three, specifically. The pass may well have delivered other tests' rows too - the
    # dispatcher drains the whole outbox, and the suite shares one database.
    for notification_id in queued:
        assert (await _row(env, notification_id)).delivered_at is not None
    assert len((await env.get(MERCHANT, staff_token)).json()) == 1
    assert len((await env.get(CUSTOMER, customer_token)).json()) == 1
    assert len((await env.get(DELIVERY, driver_token)).json()) == 1


# --- The catalogue's driver events, end to end -------------------------------------------------


async def _queue_event(env, event):
    """Queue through the real writer, the way a delivery service would."""
    async with env.sessions() as session:
        NotificationOutboxWriter(session).queue(event)
        await session.commit()


async def test_an_assignment_reaches_the_drivers_bell_and_their_phone(env):
    """The whole path: catalogue builder -> outbox -> delivery project -> delivery app list."""
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant, fcm_token="driver-phone")
    await _queue_event(
        env,
        deliveries.assigned_to_driver(
            user.id,
            "del-77",
            "ORD-2609-0012",
            slot="09:00 AM - 01:00 PM",
            customer_name="Sharma Bakery",
        ),
    )
    app = StubFcm(project_id="mbga-delivery-partner")

    await _dispatch(env, StubProjects(by_channel={"DELIVERY": app}))

    assert app.tokens == ["driver-phone"]
    _sent_token, message = app.sent[0]
    assert message.title == "New delivery assigned"
    # And it is on the list afterwards, deep-linking to the trip.
    row = (await env.get(DELIVERY, token)).json()[0]
    assert row["title"] == "New delivery assigned"
    assert "Sharma Bakery" in row["message"]
    assert row["category"] == "DELIVERY"
    assert row["referenceType"] == "DELIVERY"
    assert row["referenceId"] == "del-77"


async def test_a_cancellation_reaches_the_driver_as_critical(env):
    """The one delivery notification that has to interrupt: the van may be at the gate."""
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant)
    await _queue_event(env, deliveries.cancelled_in_transit(user.id, "del-78", "ORD-2609-0013"))

    row = (await env.get(DELIVERY, token)).json()[0]

    assert row["title"] == "Order cancelled - do not deliver"
    assert row["severity"] == "CRITICAL"


async def test_an_assignment_and_its_reassignment_both_arrive(env):
    """Two events about the same trip, and both have to land.

    Keyed on the order they would have collided on the outbox's uniqueness constraint the
    second time a job moved, and the driver would never be told it was taken back.
    """
    _staff_token, merchant, _u = await staff(env)
    token, user, _m = await driver(env, merchant)
    await _queue_event(env, deliveries.assigned_to_driver(user.id, "del-79", "ORD-2609-0014"))
    await _queue_event(
        env,
        deliveries.unassigned_from_driver(
            user.id, "del-79", "ORD-2609-0014", reason="Van breakdown."
        ),
    )

    titles = [row["title"] for row in (await env.get(DELIVERY, token)).json()]

    assert sorted(titles) == ["Delivery reassigned", "New delivery assigned"]


async def test_the_office_is_not_copied_on_every_assignment(env):
    """A job is one driver's to do. Staff have the dispatch board for that."""
    staff_token, merchant, _u = await staff(env)
    _token, user, _m = await driver(env, merchant)
    await _queue_event(env, deliveries.assigned_to_driver(user.id, "del-80", "ORD-2609-0015"))

    assert (await env.get(MERCHANT, staff_token)).json() == []


async def test_the_customers_delivery_updates_are_not_the_drivers(env):
    """`out_for_delivery` is written for the customer; it must not land on the driver's bell."""
    _staff_token, merchant, _u = await staff(env)
    customer_token, profile, _cu = await customer(env, merchant)
    driver_token, _user, _m = await driver(env, merchant)
    await _queue_event(
        env,
        deliveries.out_for_delivery(profile.id, "ord-9", "ORD-2609-0016", driver_name="Mohan Lal"),
    )

    assert len((await env.get(CUSTOMER, customer_token)).json()) == 1
    assert (await env.get(DELIVERY, driver_token)).json() == []


# --- The driver's device is registered on the delivery project ---------------------------------


async def test_a_drivers_token_is_registered_against_the_delivery_channel(env):
    """Which is what routes their push through `mbga-delivery-partner`."""
    _staff_token, merchant, _u = await staff(env)
    _token, user, _m = await driver(env, merchant, fcm_token="driver-phone")

    channel = await env.scalar(
        select(LoginSession.login_channel).where(LoginSession.push_token == "driver-phone")
    )

    assert channel == "DELIVERY"
    assert user


async def test_a_driver_still_belongs_to_their_merchant(env):
    """Reading only their own bucket is a notification rule, not a tenancy one."""
    _staff_token, merchant, _u = await staff(env)
    _token, user, _m = await driver(env, merchant)

    profile = await env.scalar(select(DeliveryProfile).where(DeliveryProfile.user_id == user.id))

    assert profile.merchant_id == merchant.id
    assert datetime.now(UTC)
