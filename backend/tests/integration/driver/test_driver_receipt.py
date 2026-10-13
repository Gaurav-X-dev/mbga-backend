"""What the completion screen says about the money, after an arrears collection.

The app sent 1,819 - today's 1,390 plus 429 of what stood - and `/verify-customer-otp` came
back saying 1,390 collected and 1,390 payable, as though the rest had been dropped. It had not:
it was applied to the older invoices. The block simply could not see past this delivery's own
invoice, and `method` was the literal string "cash" whatever had happened.
"""

import pytest
from sqlalchemy import select

from app.modules.payments.models import Invoice
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import handover, payable_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def test_the_handover_response_carries_the_whole_collection(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    verified = await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    payment = verified.json()["payment"]
    assert payment["amountCollected"] == pytest.approx(float(payable))
    assert payment["appliedToThisDelivery"] == pytest.approx(float(payable))
    assert payment["appliedToPreviousDue"] == 0


async def test_the_method_is_the_real_one(env):
    """It was hard-coded to "cash" on every single handover."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    verified = await handover(
        env, token, slip, [("LPG_19KG", 2)], method="UPI", amount=payable
    )

    assert verified.json()["payment"]["method"] == "upi"


async def test_nothing_collected_says_so(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    verified = await handover(env, token, slip, [("LPG_19KG", 2)], amount=0)

    payment = verified.json()["payment"]
    assert payment["amountCollected"] == 0
    assert payment["split"] == "partial"
    assert await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert DRIVER_DELIVERIES
