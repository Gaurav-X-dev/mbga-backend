"""What a customer sees of their own account, and what they cannot see or do.

Both apps read the same invoice and payment rows, so the scoping is the whole safety story
here. A customer reaching another customer's invoice would be a data breach, not a cosmetic
bug - and the summary at the top of their Payments tab is the number they act on.
"""

import pytest

from app.modules.payments.constants import ReconciliationStatus
from tests.integration.payments.conftest import (
    CUSTOMER_API,
    MERCHANT,
    billed,
    invoice_now,
    pay,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

CUSTOMER_AUTH = f"{CUSTOMER_API}/auth"


async def customer_token(env, customer) -> str:
    """Sign the customer in on their own channel.

    Their `users` row is created here because these profiles are inserted directly rather than
    through registration, which is what would normally create it. Same helper the order suite
    uses, imported rather than copied.
    """
    from tests.integration.orders.conftest import customer_token as sign_in

    return await sign_in(env, customer)


# --- The summary -----------------------------------------------------------------------------


async def test_the_summary_adds_up(env):
    token, _merchant, customer, invoice = await billed(env)
    total = invoice["totalAmount"]
    await pay(env, token, invoice, total // 2, "CASH")

    summary = await env.get(f"{MERCHANT}/customers/{customer.id}/payments/summary", token)

    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["totalInvoiced"] == total
    assert body["totalPaid"] == total // 2
    assert body["runningBalance"] == total - total // 2
    assert body["lastPaymentAt"] is not None


async def test_an_invalid_payment_is_not_a_last_payment(env):
    """Money that never arrived is not evidence the customer has paid."""
    token, _merchant, customer, invoice = await billed(env)
    recorded = await pay(
        env, token, invoice, invoice["totalAmount"], "UPI", reference="UPI-001"
    )
    await env.post(
        f"{MERCHANT}/payments/{recorded.json()['id']}/reconcile",
        token,
        {"reconciled": False, "reason": "UTR not found"},
    )

    summary = await env.get(f"{MERCHANT}/customers/{customer.id}/payments/summary", token)

    body = summary.json()
    assert body["lastPaymentAt"] is None
    assert body["totalPaid"] == 0
    assert body["runningBalance"] == invoice["totalAmount"]


async def test_a_customer_with_no_invoices_owes_nothing(env):
    """Zeroes, not an error - a new customer opens this screen too."""
    from tests.integration.deliveries.conftest import dispatch_staff, make_customer
    from tests.integration.payments.conftest import BOOKS

    token, merchant, _user = await dispatch_staff(env, permissions=BOOKS)
    customer = await make_customer(env, merchant)

    summary = await env.get(f"{MERCHANT}/customers/{customer.id}/payments/summary", token)

    assert summary.status_code == 200, summary.text
    assert summary.json() == {
        "totalInvoiced": 0,
        "totalPaid": 0,
        "runningBalance": 0,
        "overdueAmount": 0,
        "lastPaymentAt": None,
    }


# --- The customer's own channel ----------------------------------------------------------------


async def test_a_customer_reads_their_own_invoice(env):
    _token, _merchant, customer, invoice = await billed(env)
    token = await customer_token(env, customer)

    listed = await env.get(f"{CUSTOMER_API}/invoices", token)

    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [invoice["id"]]


async def test_a_customer_never_sees_another_customer_s_invoice(env):
    _t_a, _m_a, customer_a, invoice_a = await billed(env)
    _t_b, _m_b, customer_b, _invoice_b = await billed(env)
    token_b = await customer_token(env, customer_b)

    listed = await env.get(f"{CUSTOMER_API}/invoices", token_b)
    direct = await env.get(f"{CUSTOMER_API}/invoices/{invoice_a['id']}", token_b)

    assert invoice_a["id"] not in [row["id"] for row in listed.json()]
    assert direct.status_code == 404
    assert customer_a.id != customer_b.id


async def test_a_merchant_cannot_read_another_merchant_s_customer_summary(env):
    """The summary is an aggregate, so it has no row of its own to be scoped by.

    Every other payment read is a row the scope filter catches, which is why this one needed a
    check of its own: without it a guessed customer id answered with another merchant's books.
    """
    token_a, _merchant_a, customer_a, invoice_a = await billed(env)
    await pay(env, token_a, invoice_a, invoice_a["totalAmount"] // 2, "CASH")
    token_b, _merchant_b, _customer_b, _invoice_b = await billed(env)

    response = await env.get(f"{MERCHANT}/customers/{customer_a.id}/payments/summary", token_b)

    assert response.status_code == 404, response.text


async def test_a_customer_cannot_read_another_s_summary(env):
    _t_a, _m_a, customer_a, _invoice_a = await billed(env)
    _t_b, _m_b, customer_b, _invoice_b = await billed(env)
    token_b = await customer_token(env, customer_b)

    response = await env.get(
        f"{CUSTOMER_API}/customers/{customer_a.id}/payments/summary", token_b
    )

    assert response.status_code == 404


async def test_a_customer_cannot_record_a_payment_against_themselves(env):
    """Recording a collection is an act of the merchant's books.

    The person doing it is holding the notes or looking at a bank statement - which is not
    something the platform can let a customer assert about their own invoice.
    """
    _token, _merchant, customer, invoice = await billed(env)
    token = await customer_token(env, customer)

    response = await env.post(
        f"{CUSTOMER_API}/payments",
        token,
        {"invoiceId": invoice["id"], "amount": 100, "mode": "CASH"},
    )

    assert response.status_code in (403, 404, 405)
    assert (await invoice_now(env, _token, invoice["id"]))["paidAmount"] == 0


async def test_a_customer_sees_their_own_receipts(env):
    staff_token, _merchant, customer, invoice = await billed(env)
    await pay(env, staff_token, invoice, invoice["totalAmount"], "CASH")
    token = await customer_token(env, customer)

    listed = await env.get(f"{CUSTOMER_API}/payments", token)

    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["reconciliationStatus"] == ReconciliationStatus.RECONCILED.value


# --- The customer record itself -----------------------------------------------------------------


async def test_the_customer_record_now_carries_a_real_balance(env):
    """It was a hardcoded zero until invoices existed."""
    token, _merchant, customer, invoice = await billed(env)

    record = await env.get(f"{MERCHANT}/customers/{customer.id}", token)

    assert record.status_code == 200, record.text
    assert record.json()["runningBalance"] == invoice["totalAmount"]


async def test_the_balance_falls_as_the_customer_pays(env):
    token, _merchant, customer, invoice = await billed(env)
    await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    record = await env.get(f"{MERCHANT}/customers/{customer.id}", token)

    assert record.json()["runningBalance"] == 0
