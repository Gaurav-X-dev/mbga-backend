"""A cancelled order stays cancelled, whatever arrives next and in whatever order.

This file exists because of a real report: an order the customer had cancelled came back as out
for delivery. The transition table always forbade that - `CANCELLED` maps to the empty set - so
the refusal was never the problem. The read was. Both sides loaded the order without a lock, so a
cancellation and a dispatch each checked their own snapshot, each saw a status taken before the
other committed, and the later writer overwrote the earlier. The dispatch is the slower request,
so `CANCELLED` is the one that lost.

What is pinned here is therefore the *outcome* under a race, not just the rule in isolation: that
whichever request gets there second is refused rather than believed, and that the refusal names
the cancellation so a stale delivery screen knows to reload rather than retry.
"""

import asyncio

from sqlalchemy import func, select

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.deliveries.constants import LIVE_STATUSES
from app.modules.deliveries.models import DeliverySlip
from tests.integration.deliveries.conftest import ready_to_dispatch
from tests.integration.driver.conftest import DRIVER_DELIVERIES, driver_token
from tests.integration.orders.conftest import ORDERS, code_of, post

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def cancel(env, token, order_id: str, reason: str = "Customer called it off"):
    return await post(env, f"{ORDERS}/{order_id}/cancel", token, {"reason": reason})


async def status_of(env, order_id: str) -> str:
    async with env.sessions() as db:
        return await db.scalar(select(Order.status).where(Order.id == order_id))


# --- The refusal ------------------------------------------------------------------------------


async def test_a_cancelled_order_cannot_be_dispatched(env):
    """The headline case: the van must not go out for an order that was called off."""
    token, _merchant, order, slip, driver = await ready_to_dispatch(env)
    assert (await cancel(env, token, order["id"])).status_code == 200
    delivery_token = await driver_token(env, driver)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", delivery_token
    )

    assert response.status_code == 409
    assert code_of(response) == "ORDER_ALREADY_CANCELLED"
    assert await status_of(env, order["id"]) == "CANCELLED"


async def test_the_refusal_tells_a_stale_screen_to_reload(env):
    """A driver's phone showing yesterday's queue needs a code it can branch on.

    `INVALID_ORDER_STATUS` would say the move was illegal. This says the order is gone, which is
    the difference between offering a retry and reloading it as cancelled.
    """
    token, _merchant, order, slip, driver = await ready_to_dispatch(env)
    await cancel(env, token, order["id"])
    delivery_token = await driver_token(env, driver)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", delivery_token
    )

    body = response.json()["detail"]
    assert body["code"] == "ORDER_ALREADY_CANCELLED"
    assert "cancelled" in body["message"].lower()


# --- The race --------------------------------------------------------------------------------


async def test_cancelling_and_dispatching_at_once_never_resurrects_the_order(env):
    """Fired together, on separate connections, which is the only way to reproduce the bug.

    The office may now call off a round that is already out, so **both** requests succeeding is
    a correct outcome: the van set off and was recalled a moment later. What must never happen
    is the other order of events - a cancellation followed by a dispatch that moves the order
    anyway, which is what the lock was added to stop and what the trail used to show as
    `CANCELLED` then `OUT_FOR_DELIVERY`.

    So this asserts the invariant the file is named for: once an order reads `CANCELLED`, it
    stays cancelled, and the slip that was carrying it is not left live.
    """
    token, _merchant, order, slip, driver = await ready_to_dispatch(env)
    delivery_token = await driver_token(env, driver)

    cancelling, dispatching = await asyncio.gather(
        cancel(env, token, order["id"]),
        env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", delivery_token),
        return_exceptions=True,
    )

    codes = [r.status_code for r in (cancelling, dispatching) if hasattr(r, "status_code")]
    assert 200 in codes, f"neither request succeeded: {codes}"

    final = await status_of(env, order["id"])
    if hasattr(cancelling, "status_code") and cancelling.status_code == 200:
        assert final == "CANCELLED", "the cancellation succeeded but the order moved anyway"
        async with env.sessions() as db:
            live = await db.scalar(
                select(func.count())
                .select_from(DeliverySlip)
                .where(
                    DeliverySlip.order_id == order["id"],
                    DeliverySlip.status.in_(tuple(LIVE_STATUSES)),
                )
            )
        assert live == 0, "the order was cancelled but its slip is still on the driver's list"
    else:
        assert final == "OUT_FOR_DELIVERY", "the dispatch won but the order did not move"


# --- The trail -------------------------------------------------------------------------------


async def test_the_trail_names_the_app_and_the_role(env):
    """Without these the trail cannot answer which app moved an order, only that someone did."""
    _token, _merchant, order, slip, driver = await ready_to_dispatch(env)
    delivery_token = await driver_token(env, driver)
    await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", delivery_token)

    async with env.sessions() as db:
        rows = (
            await db.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == order["id"])
                .order_by(OrderStatusHistory.changed_at)
            )
        ).all()

    dispatched = [row for row in rows if row.status == "OUT_FOR_DELIVERY"]
    assert dispatched, [row.status for row in rows]
    moved = dispatched[-1]
    assert moved.previous_status == "CONFIRMED"
    assert moved.source == "DELIVERY_APP"
    assert moved.changed_by_role
    assert moved.changed_by_user_id


async def test_a_cancellation_is_trailed_like_any_other_move(env):
    """It used to write its own history row beside `advance()` rather than through it."""
    token, _merchant, order, _slip, _driver = await ready_to_dispatch(env)

    await cancel(env, token, order["id"], reason="Shop shut for the festival")

    async with env.sessions() as db:
        row = await db.scalar(
            select(OrderStatusHistory)
            .where(
                OrderStatusHistory.order_id == order["id"],
                OrderStatusHistory.status == "CANCELLED",
            )
            .order_by(OrderStatusHistory.changed_at.desc())
        )
    assert row is not None
    assert row.previous_status == "CONFIRMED"
    assert row.source == "MERCHANT_APP"
    assert row.note == "Shop shut for the festival"
