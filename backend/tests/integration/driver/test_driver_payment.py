"""The money a driver collects at the gate, and what happens to it.

The Delivery App has always sent a payment block when the driver confirms his counts - mode,
amount, what is still pending - and the backend threw every bit of it away. No payment row was
written, so an invoice stayed at zero paid however much cash came back on the van, the delivery
receipt said "cash" because there was nothing to read, and a customer's balance counted only
what the office had typed in by hand.

These tests pin the collection to the rows it belongs to: a payment against the invoice, in the
mode the driver chose, with the customer's balance moving by that amount and no further.
"""

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order
from app.modules.payments.models import Invoice, Payment
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


def confirmation(delivered, *, method="CASH", amount, empties=None, **extra):
    """The body the Delivery App posts to `/confirm`."""
    return {
        "deliveredItems": [
            {"cylinderType": kind, "quantity": quantity} for kind, quantity in delivered
        ],
        "collectedEmpties": [
            {"cylinderType": kind, "quantity": quantity} for kind, quantity in (empties or [])
        ],
        "payment": {
            "method": method,
            "split": "full",
            "amountCollected": amount,
            "payableAmount": amount,
            "pendingBalance": 0,
            **extra,
        },
        "driverNotes": "Handed over at the gate",
    }


async def payable_of(env, slip) -> int:
    order = await env.scalar(select(Order).where(Order.id == slip["orderId"]))
    return order.total_amount


async def handover(env, token, slip, delivered, **payment):
    """Confirm the counts, then complete the handover with the customer's code."""
    confirmed = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm", token, confirmation(delivered, **payment)
    )
    assert confirmed.status_code == 200, confirmed.text
    verified = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )
    assert verified.status_code == 200, verified.text
    return verified


async def test_cash_taken_at_the_gate_lands_on_the_invoice(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.paid_amount == payable
    assert invoice.balance == 0
    assert invoice.status == "PAID"


async def test_the_payment_records_how_it_was_paid_and_who_took_it(env):
    _staff, token, slip, driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(
        env,
        token,
        slip,
        [("LPG_19KG", 2)],
        method="UPI",
        amount=payable,
        reference="UTR9988776655",
    )

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    payment = await env.scalar(select(Payment).where(Payment.invoice_id == invoice.id))
    assert payment.mode == "UPI"
    assert payment.amount_collected == payable
    assert payment.reference == "UTR9988776655"
    assert payment.collected_by_user_id == driver.id
    # UPI is evidence of nothing until somebody finds it in a statement; cash is the money itself.
    assert payment.reconciliation_status == "PENDING"


async def test_a_part_payment_leaves_the_rest_owing(env):
    """A customer paying half at the gate is ordinary, and the other half must still be chased."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=payable // 2)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.paid_amount == payable // 2
    assert invoice.balance == payable - payable // 2
    assert invoice.status == "PARTIAL"


async def test_paying_nothing_records_no_payment_at_all(env):
    """Not a zero payment. A zero row is a collection that happened, and this one did not."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.paid_amount == 0
    assert invoice.status == "UNPAID"
    assert await env.scalar(select(Payment.id).where(Payment.invoice_id == invoice.id)) is None


async def test_more_than_the_delivery_comes_to_is_refused(env):
    """The platform has no customer wallet, so over-collection is money with nowhere to sit."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=payable + 1),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PAYMENT_EXCEEDS_PAYABLE"


async def test_a_part_delivery_may_only_be_collected_for_what_was_handed_over(env):
    """Two of four cylinders is half the bill, whatever the order said when it was placed."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))
    whole_order = await payable_of(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=whole_order),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PAYMENT_EXCEEDS_PAYABLE"


async def test_upi_is_collectable_without_a_reference(env):
    """The UTR appears on the *customer's* phone, and the driver's screen has nowhere to put it.
    Demanding one made UPI uncollectable at the gate, which is where UPI is collected."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], method="UPI", amount=payable),
    )

    assert response.status_code == 200, response.text


async def test_an_unreferenced_upi_payment_waits_for_the_bank(env):
    """It is recorded and counted, but not trusted: the office settles it against the statement,
    matching on the amount and the time."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], method="UPI", amount=payable)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    payment = await env.scalar(select(Payment).where(Payment.invoice_id == invoice.id))
    assert payment.reconciliation_status == "PENDING"
    assert payment.reference is None


async def test_cash_needs_no_evidence(env):
    """The person typing it in is holding the notes."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=payable),
    )

    assert response.status_code == 200, response.text


async def test_an_unknown_payment_mode_is_refused(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], method="BITCOIN", amount=10),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "PAYMENT_MODE_INVALID"


async def test_the_receipt_says_how_it_was_actually_paid(env):
    """It used to say "cash" whatever had happened, because nothing was recorded to read."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)
    await handover(
        env, token, slip, [("LPG_19KG", 2)], method="UPI", amount=payable, reference="UTR123456"
    )

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)

    assert detail.status_code == 200, detail.text
    payment = detail.json()["payment"]
    assert payment["method"] == "upi"
    assert payment["split"] == "full"
    assert payment["amountPaid"] == payable
    assert payment["pendingBalance"] == 0


async def test_an_unpaid_delivery_names_no_payment_method(env):
    """`null`, not "cash". Nobody paid in cash; nobody paid at all."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0)

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)

    payment = detail.json()["payment"]
    assert payment["method"] is None
    assert payment["split"] == "unpaid"
