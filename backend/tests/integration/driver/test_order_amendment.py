"""Changing an order at the gate.

`PUT /{deliveryId}/update-items` existed and did nothing. It took the new basket, threw it
away, wrote the reason onto the slip as a note and returned 200 - so the delivery app could
finish the doorstep flow while the order it was meant to change sat untouched.

The driver is standing there with two 19 KG on the van and the customer asks for a third, or
decides against the second. The order was fixed the moment it was confirmed, so the only
answers were a second order - a second bill with a second number for one visit - or cancelling
the whole thing and placing it again, which throws away its number and its history.

The prices are the delicate part. A line the customer already agreed to keeps the rate it was
agreed at; only a size that is new to the order is priced at today's rate.
"""

import pytest
from sqlalchemy import select, update

from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.platform_settings.models import SINGLETON_ID, PlatformSettings
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import confirmation

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def amend(env, token, slip, *lines, reason: str = "Customer asked at the gate"):
    return await env.client.put(
        f"{DRIVER_DELIVERIES}/{slip['id']}/update-items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "updatedItems": [{"cylinderType": kind, "quantity": qty} for kind, qty in lines],
            "reason": reason,
        },
    )


async def order_of(env, slip) -> Order:
    async with env.sessions() as db:
        return await db.scalar(select(Order).where(Order.id == slip["orderId"]))


async def lines_of(env, slip) -> dict[str, OrderItem]:
    async with env.sessions() as db:
        rows = await db.scalars(select(OrderItem).where(OrderItem.order_id == slip["orderId"]))
        return {row.cylinder_type: row for row in rows}


async def slip_lines(env, slip) -> dict[str, int]:
    async with env.sessions() as db:
        rows = await db.scalars(
            select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip["id"])
        )
        return {row.cylinder_type: row.quantity for row in rows}


# --- What the customer asked for ---------------------------------------------------------------


async def test_the_customer_can_take_one_more(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, token, slip, ("LPG_19KG", 3))

    assert response.status_code == 200, response.text
    assert (await lines_of(env, slip))["LPG_19KG"].quantity == 3


async def test_credit_limit_blocks_a_more_expensive_doorstep_update(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    order = await order_of(env, slip)
    await env.execute(
        update(PlatformSettings)
        .where(PlatformSettings.id == SINGLETON_ID)
        .values(credit_limit_enabled=True)
    )
    await env.execute(
        update(CustomerProfile)
        .where(CustomerProfile.id == order.customer_id)
        .values(credit_enabled=True, credit_limit=order.total_amount)
    )

    response = await amend(env, token, slip, ("LPG_19KG", 3))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"
    assert (await lines_of(env, slip))["LPG_19KG"].quantity == 2


async def test_the_customer_can_take_one_fewer(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    assert (await amend(env, token, slip, ("LPG_19KG", 1))).status_code == 200

    assert (await lines_of(env, slip))["LPG_19KG"].quantity == 1


async def test_a_size_the_order_never_had_can_be_added(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_5KG", 1))

    assert response.status_code == 200, response.text
    assert set(await lines_of(env, slip)) == {"LPG_19KG", "LPG_5KG"}


async def test_a_size_left_out_is_dropped(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2), ("LPG_5KG", 2))

    assert (await amend(env, token, slip, ("LPG_19KG", 2))).status_code == 200

    assert set(await lines_of(env, slip)) == {"LPG_19KG"}


async def test_a_zero_drops_the_line_too(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2), ("LPG_5KG", 2))

    assert (await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_5KG", 0))).status_code == 200

    assert set(await lines_of(env, slip)) == {"LPG_19KG"}


# --- The money ---------------------------------------------------------------------------------


async def test_an_agreed_price_is_not_re_quoted(env):
    """The customer agreed to this rate at placement; adding a cylinder must not move it."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    agreed = (await lines_of(env, slip))["LPG_19KG"].unit_price

    await amend(env, token, slip, ("LPG_19KG", 3), ("LPG_5KG", 1))

    assert (await lines_of(env, slip))["LPG_19KG"].unit_price == agreed


async def test_the_order_total_follows_the_new_lines(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    unit = (await lines_of(env, slip))["LPG_19KG"].unit_price

    await amend(env, token, slip, ("LPG_19KG", 3))

    order = await order_of(env, slip)
    assert order.total_amount == unit * 3
    assert order.total_cylinders == 3


async def test_the_gst_still_breaks_out_of_the_total(env):
    """GST comes out of the figure, never on top of it - the rule the whole bill rests on."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await amend(env, token, slip, ("LPG_19KG", 3), ("LPG_5KG", 2))

    order = await order_of(env, slip)
    assert order.subtotal + order.gst_amount == order.total_amount


async def test_a_new_line_is_priced_not_free(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_5KG", 1))

    added = (await lines_of(env, slip))["LPG_5KG"]
    assert added.unit_price > 0
    assert added.line_total == added.unit_price


# --- The slip the driver is holding --------------------------------------------------------------


async def test_the_slip_carries_the_new_count(env):
    """Useless otherwise: he cannot hand over what the slip does not say he has."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await amend(env, token, slip, ("LPG_19KG", 3))

    assert (await slip_lines(env, slip))["LPG_19KG"] == 3
    async with env.sessions() as db:
        row = await db.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))
    assert row.cylinders_allocated == 3


async def test_the_added_cylinder_can_then_be_handed_over(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await amend(env, token, slip, ("LPG_19KG", 3))

    confirmed = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 3)], amount=0, empties=[]),
    )

    assert confirmed.status_code == 200, confirmed.text


async def test_the_amended_order_is_what_gets_billed(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await amend(env, token, slip, ("LPG_19KG", 3))
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 3)], amount=0, empties=[]),
    )

    receipt = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["totalDeliveredQuantity"] == 3


# --- The trail ------------------------------------------------------------------------------------


async def test_the_change_is_written_on_the_orders_trail(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await amend(env, token, slip, ("LPG_19KG", 3))

    async with env.sessions() as db:
        trail = list(
            await db.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == slip["orderId"])
                .order_by(OrderStatusHistory.changed_at)
            )
        )
    assert "changed at the gate" in (trail[-1].note or "").lower()
    # A note on the timeline, not a step in it.
    assert trail[-1].previous_status == trail[-1].status


async def test_the_order_keeps_its_number(env):
    """The whole point of amending rather than cancelling and placing again."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    before = (await order_of(env, slip)).order_number

    await amend(env, token, slip, ("LPG_19KG", 3))

    assert (await order_of(env, slip)).order_number == before


# --- What it refuses --------------------------------------------------------------------------------


async def test_an_empty_basket_is_refused(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, token, slip, ("LPG_19KG", 0))

    assert response.status_code == 422, response.text


async def test_a_billed_delivery_is_not_amended(env):
    """From the moment the code is read out the bill exists, and a bill is not edited."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=0, empties=[]),
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    response = await amend(env, token, slip, ("LPG_19KG", 3))

    assert response.status_code == 409, response.text


async def test_an_unknown_cylinder_type_is_refused(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_900KG", 1))

    assert response.status_code == 422, response.text


async def test_another_drivers_delivery_is_not_found(env):
    _staff, _token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    _staff2, other_token, _slip2, _driver2 = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, other_token, slip, ("LPG_19KG", 3))

    assert response.status_code == 404, response.text


async def test_the_reason_reaches_the_trail(env):
    """Why the order changed is the question the office asks about an amended bill."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await amend(env, token, slip, ("LPG_19KG", 3), reason="Customer wanted one more")

    async with env.sessions() as db:
        trail = list(
            await db.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == slip["orderId"])
                .order_by(OrderStatusHistory.changed_at)
            )
        )
    assert "Customer wanted one more" in (trail[-1].note or "")


async def test_a_new_line_is_priced_as_the_doorstep_sheet_quoted_it(env):
    """The sheet and the bill price off the same rate card, or the customer is told one figure
    and charged another."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    sheet = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/available-cylinder-types", token)
    assert sheet.status_code == 200, sheet.text
    quoted = {row["cylinderType"]: row["unitPrice"] for row in sheet.json()["cylinderTypes"]}

    await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_5KG", 1))

    assert (await lines_of(env, slip))["LPG_5KG"].unit_price == quoted["LPG_5KG"]


async def test_a_cylinder_the_customer_may_not_buy_is_refused(env):
    """A retail customer cannot be sold a hippo at the gate any more than online."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await amend(env, token, slip, ("LPG_19KG", 2), ("LPG_422KG_HIPPO", 1))

    assert response.status_code == 422, response.text
