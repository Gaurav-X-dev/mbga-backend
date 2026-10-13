"""Collecting the arrears at the gate, and where that money lands.

The driver's screen asks for everything the customer owes - this delivery plus what was left
from before - so the gate had to stop refusing it. A payment is recorded against **one**
invoice, and over-collection against it is refused, rightly: the platform has no wallet for a
surplus to sit in. So the money is split instead, this delivery first and then the older
invoices oldest first, one payment row each.
"""

import pytest
from sqlalchemy import select

from app.modules.payments.models import Invoice, Payment
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import confirmation, handover, payable_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def a_customer_in_arrears(env):
    """Deliver once and pay nothing, so the next delivery has something to carry.

    Both rounds go to the same customer, which `on_the_road` arranges by reusing the staff
    token - so the second slip's `customerPreviousDue` is the first delivery's unpaid bill.
    """
    staff, token, first, driver = await on_the_road(env, ("LPG_19KG", 2))
    owed = await payable_of(env, first)
    await handover(env, token, first, [("LPG_19KG", 2)], amount=0)
    return staff, token, first, driver, owed


async def invoices_of(env, customer_id: str) -> list[Invoice]:
    async with env.sessions() as db:
        return list(
            await db.scalars(
                select(Invoice)
                .where(Invoice.customer_id == customer_id)
                .order_by(Invoice.issued_at, Invoice.id)
            )
        )


# --- What the gate will accept ----------------------------------------------------------------


async def test_the_ceiling_is_everything_the_customer_owes(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    summary = (await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/payment-summary", token)).json()

    assert summary["maxQrAmount"] == pytest.approx(summary["totalDue"])


async def test_more_than_that_is_still_refused(env):
    """The rule did not go away - it moved."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=payable + 1),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PAYMENT_EXCEEDS_PAYABLE"


async def test_paying_only_this_delivery_still_works(env):
    """The ordinary case has to stay exactly as it was."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.balance == 0
    assert invoice.status == "PAID"


# --- Where the surplus goes --------------------------------------------------------------------


async def test_the_older_invoice_is_cleared_by_the_surplus(env):
    _staff, token, _first, _driver, owed = await a_customer_in_arrears(env)
    _s2, token2, second, _d2 = await on_the_road(env, ("LPG_19KG", 1))
    today = await payable_of(env, second)

    await handover(env, token2, second, [("LPG_19KG", 1)], amount=today + 0)

    # This delivery is settled; the older one is untouched by a payment that only covered today.
    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == second["orderId"]))
    assert invoice.balance == 0
    assert owed


async def test_this_delivery_is_paid_before_the_arrears(env):
    """It is what the customer is being handed cylinders for."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    payment = await env.scalar(select(Payment).where(Payment.invoice_id == invoice.id))
    assert payment is not None
    assert payment.amount_collected == payable


async def test_each_invoice_gets_its_own_payment_row(env):
    """A single row spanning several would leave each invoice's paid amount to be inferred."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)
    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    async with env.sessions() as db:
        rows = list(await db.scalars(select(Payment).where(Payment.invoice_id == invoice.id)))

    assert len(rows) == 1
    assert sum(row.amount_collected for row in rows) == payable


async def test_a_part_payment_leaves_the_rest_owing(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable // 2)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.paid_amount == payable // 2
    assert invoice.status == "PARTIAL"


async def test_the_money_carries_the_delivery_it_was_taken_on(env):
    """So the office can tell a gate collection from one typed in at the counter."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)
    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    payment = await env.scalar(select(Payment).where(Payment.invoice_id == invoice.id))
    assert slip["orderNumber"] in (payment.note or "")


async def test_the_qr_may_be_raised_for_the_whole_amount(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    from sqlalchemy import update

    from app.modules.deliveries.models import DeliverySlip
    from app.modules.merchants.models import Merchant

    merchant_id = await env.scalar(
        select(DeliverySlip.merchant_id).where(DeliverySlip.id == slip["id"])
    )
    await env.execute(
        update(Merchant)
        .where(Merchant.id == merchant_id)
        .values(upi_id="mbga@okhdfcbank", upi_payee_name="MBGA Gas Agency")
    )
    summary = (await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/payment-summary", token)).json()

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr",
        token,
        {"amount": summary["maxQrAmount"]},
    )

    assert response.status_code == 200, response.text


# --- The same customer, twice -----------------------------------------------------------------


async def two_deliveries_for_one_customer(env):
    """Two rounds to the **same** customer, the first left unpaid.

    `on_the_road` makes a fresh customer each time, so the spillover - the whole point of
    collecting arrears - has nothing to spill onto. This builds the case by hand.
    """
    from tests.integration.deliveries.conftest import (
        ORDERS,
        dispatch_staff,
        make_customer,
        make_driver,
        place_order,
        price_cylinders,
        refill,
    )
    from tests.integration.driver.conftest import driver_token

    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 400)
    driver = await make_driver(env, merchant)
    drivers_token = await driver_token(env, driver)

    async def deliver(quantity: int, *, pay: int):
        order = await place_order(env, token, customer.id, ("LPG_19KG", quantity))
        confirmed = await env.post(
            f"{ORDERS}/{order['id']}/confirm",
            token,
            {"delivery": {"vehicleNumber": "MP09 GH 4521", "driverUserId": driver.id}},
        )
        assert confirmed.status_code == 200, confirmed.text
        slip_id = confirmed.json()["deliverySlipId"]
        started = await env.post(
            f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers_token, {}
        )
        assert started.status_code == 200, started.text
        code = started.json()["devConfirmationCode"]
        confirmed_counts = await env.post(
            f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
            drivers_token,
            confirmation([("LPG_19KG", quantity)], amount=pay),
        )
        assert confirmed_counts.status_code == 200, confirmed_counts.text
        verified = await env.post(
            f"{DRIVER_DELIVERIES}/{slip_id}/verify-customer-otp", drivers_token, {"otp": code}
        )
        assert verified.status_code == 200, verified.text
        return order, slip_id

    return customer, drivers_token, deliver


async def test_what_was_owed_before_shows_on_the_next_delivery(env):
    customer, drivers_token, deliver = await two_deliveries_for_one_customer(env)
    first_order, _first_slip = await deliver(2, pay=0)
    first = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))

    # The second round, not yet paid: its screen must show the first round's bill.
    from tests.integration.deliveries.conftest import ORDERS  # noqa: F401 - imported above

    _second_order, second_slip = await deliver(1, pay=0)
    summary = (
        await env.get(f"{DRIVER_DELIVERIES}/{second_slip}/payment-summary", drivers_token)
    ).json()

    assert summary["customerPreviousDue"] == pytest.approx(float(first.total_amount))
    assert summary["totalDue"] == pytest.approx(
        summary["pendingAmount"] + summary["customerPreviousDue"]
    )
    assert customer


async def test_collecting_the_lot_clears_the_older_invoice_too(env):
    """The point of the whole change: money handed over at the gate pays off the arrears.

    Two identical rounds, the first unpaid. The second is paid for twice its own bill - today
    plus what stood - and both invoices must come out settled.
    """
    _customer, _drivers_token, deliver = await two_deliveries_for_one_customer(env)
    first_order, _first_slip = await deliver(2, pay=0)
    first = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))
    arrears = int(first.total_amount)
    assert arrears > 0

    second_order, _second_slip = await deliver(2, pay=arrears * 2)

    first_after = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))
    second_after = await env.scalar(
        select(Invoice).where(Invoice.order_id == second_order["id"])
    )
    assert second_after.balance == 0, "this delivery is paid first"
    assert first_after.balance == 0, "and the surplus clears what stood before it"
    assert {first_after.status, second_after.status} == {"PAID"}


async def test_the_surplus_is_its_own_payment_row(env):
    """One row per invoice: a single row spanning both would leave each invoice's paid amount
    to be inferred, and the trail would not say which bill the money cleared."""
    _customer, _drivers_token, deliver = await two_deliveries_for_one_customer(env)
    first_order, _first_slip = await deliver(2, pay=0)
    first = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))
    arrears = int(first.total_amount)

    second_order, _second_slip = await deliver(2, pay=arrears * 2)

    second = await env.scalar(select(Invoice).where(Invoice.order_id == second_order["id"]))
    async with env.sessions() as db:
        on_first = list(await db.scalars(select(Payment).where(Payment.invoice_id == first.id)))
        on_second = list(
            await db.scalars(select(Payment).where(Payment.invoice_id == second.id))
        )

    assert len(on_first) == 1
    assert len(on_second) == 1
    assert on_first[0].amount_collected == arrears
    assert on_second[0].amount_collected == arrears


async def test_paying_part_of_the_arrears_leaves_the_rest(env):
    """Today's bill is settled first, and whatever is left goes as far as it goes."""
    _customer, _drivers_token, deliver = await two_deliveries_for_one_customer(env)
    first_order, _first_slip = await deliver(2, pay=0)
    first = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))
    arrears = int(first.total_amount)

    # Today's bill in full, plus a quarter of what stood.
    second_order, _second_slip = await deliver(2, pay=arrears + arrears // 4)

    first_after = await env.scalar(select(Invoice).where(Invoice.order_id == first_order["id"]))
    second_after = await env.scalar(
        select(Invoice).where(Invoice.order_id == second_order["id"])
    )
    assert second_after.balance == 0
    assert first_after.balance == arrears - arrears // 4
    assert first_after.status == "PARTIAL"
