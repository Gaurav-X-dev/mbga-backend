"""What the driver is shown about money, and where it comes from.

Every figure on the delivery app used to be a constant: 1000 per cylinder whatever its size,
1000 payable whatever the order came to, and a shift that always read five deliveries and 15,000
collected. The driver reads these out to a customer at the gate, so a made-up number is worse
than no number at all.

These tests pin the figures to the rows they belong to - the order's line prices and the
invoice's totals - and would fail again the moment a constant came back.
"""

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order, OrderItem
from tests.integration.driver.conftest import DRIVER, DRIVER_DELIVERIES, on_the_road

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def test_a_line_is_priced_from_the_order_not_a_constant(env):
    """A 19 KG and a 5 KG cannot both come to the same number."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    listed = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    assert listed.status_code == 200, listed.text
    row = [item for item in listed.json() if item["id"] == slip["id"]][0]
    line = row["items"][0]

    priced = await env.scalar(
        select(OrderItem).where(
            OrderItem.order_id == slip["orderId"],
            OrderItem.cylinder_type == "LPG_19KG",
        )
    )
    assert line["unitPrice"] == pytest.approx(float(priced.unit_price))
    assert line["unitPrice"] != 1000.0, "the old mock price is back"
    assert line["totalPrice"] == pytest.approx(float(priced.unit_price) * line["quantity"])


async def test_the_payable_total_is_the_order_s_own(env):
    """Summing line prices is not the same number: GST sits inside the order's total."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    listed = await env.get(f"{DRIVER_DELIVERIES}/today", token)
    row = [item for item in listed.json() if item["id"] == slip["id"]][0]

    order = await env.scalar(select(Order).where(Order.id == slip["orderId"]))
    assert row["billing"]["totalPayableAmount"] == pytest.approx(float(order.total_amount))
    assert row["billing"]["taxAmount"] == pytest.approx(float(order.gst_amount))


async def test_a_new_driver_has_not_delivered_anything_today(env):
    """It used to greet every driver with five deliveries and 15,000 collected, on day one."""
    _staff, token, _slip, _driver = await on_the_road(env)

    profile = await env.get(f"{DRIVER}/profile", token)

    stats = profile.json()["shiftStats"]
    assert stats["completedDeliveriesToday"] == 0
    assert stats["cashCollectedToday"] == 0
    assert stats["totalEmptiesCollectedToday"] == 0
