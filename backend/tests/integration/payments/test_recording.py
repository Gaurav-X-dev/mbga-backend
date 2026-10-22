"""Collecting money against an invoice (spec §12.5).

The invariant every one of these protects: an invoice's `paidAmount` and `balance` are a
summary of the payments applied to it. If the two can ever disagree, a merchant's books are
wrong in a way nobody notices until somebody chases a customer who has already paid.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.modules.payments.constants import InvoiceStatus, ReconciliationStatus
from app.modules.payments.models import Payment
from tests.integration.payments.conftest import (
    PAYMENTS,
    READ_ONLY,
    billed,
    invoice_now,
    pay,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


# --- The happy path --------------------------------------------------------------------------


async def test_cash_settles_the_invoice_in_full(env):
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["paymentNumber"].startswith("PAY-")
    assert body["amountCollected"] == invoice["totalAmount"]
    # Cash is reconciled the moment it is recorded - the person typing it in holds the notes.
    assert body["reconciliationStatus"] == ReconciliationStatus.RECONCILED.value
    assert body["customerRunningBalance"] == 0

    after = await invoice_now(env, token, invoice["id"])
    assert after["status"] == InvoiceStatus.PAID.value
    assert after["balance"] == 0
    assert after["paidAmount"] == invoice["totalAmount"]


async def test_a_part_payment_leaves_the_invoice_partial(env):
    token, _merchant, _customer, invoice = await billed(env)
    half = invoice["totalAmount"] // 2

    response = await pay(env, token, invoice, half, "CASH")

    assert response.status_code == 201, response.text
    after = await invoice_now(env, token, invoice["id"])
    assert after["status"] == InvoiceStatus.PARTIAL.value
    assert after["paidAmount"] == half
    assert after["balance"] == invoice["totalAmount"] - half


async def test_two_part_payments_settle_it(env):
    """Several collections on one invoice is ordinary - cash today, UPI next week."""
    token, _merchant, _customer, invoice = await billed(env)
    total = invoice["totalAmount"]
    first = total // 3

    await pay(env, token, invoice, first, "CASH")
    second = await pay(
        env, token, await invoice_now(env, token, invoice["id"]), total - first, "UPI",
        reference="UPI-4471820039",
    )

    assert second.status_code == 201, second.text
    after = await invoice_now(env, token, invoice["id"])
    assert after["status"] == InvoiceStatus.PAID.value
    assert after["paidAmount"] == total
    assert after["balance"] == 0


async def test_upi_waits_for_the_bank(env):
    """The only evidence so far is a screenshot somebody showed a driver."""
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(
        env, token, invoice, invoice["totalAmount"], "UPI", reference="UPI-4471820039"
    )

    assert response.status_code == 201, response.text
    assert response.json()["reconciliationStatus"] == ReconciliationStatus.PENDING.value
    # It still counts against the invoice - the customer has paid, the merchant is waiting.
    assert (await invoice_now(env, token, invoice["id"]))["balance"] == 0


# --- What is refused -------------------------------------------------------------------------


async def test_more_than_the_balance_is_refused(env):
    """Over-collection would be money with nowhere to sit - there is no customer wallet."""
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, invoice["totalAmount"] + 1, "CASH")

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "amount"
    assert response.json()["detail"]["fields"][0]["message"] == "Exceeds balance"
    assert (await invoice_now(env, token, invoice["id"]))["paidAmount"] == 0


@pytest.mark.parametrize("amount", [0, -100])
async def test_a_nonsense_amount_is_refused(env, amount):
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, amount, "CASH")

    assert response.status_code == 422
    assert (await invoice_now(env, token, invoice["id"]))["paidAmount"] == 0


@pytest.mark.parametrize("mode", ["UPI", "NEFT"])
async def test_a_bank_payment_without_a_reference_is_refused(env, mode):
    """Without a UTR it can never be matched against a statement - it would sit PENDING for ever."""
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, invoice["totalAmount"], mode)

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "reference"
    assert response.json()["detail"]["fields"][0]["message"] == "Reference is required"


async def test_cash_needs_no_reference(env):
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    assert response.status_code == 201, response.text


async def test_a_settled_invoice_takes_no_more_money(env):
    token, _merchant, _customer, invoice = await billed(env)
    await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    response = await pay(env, token, invoice, 1, "CASH")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVOICE_ALREADY_PAID"


async def test_a_payment_cannot_be_dated_in_the_future(env):
    """It would put money in a collection report before it exists."""
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(
        env, token, invoice, 100, "CASH", paidAt="2099-01-01T00:00:00.000Z"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "paidAt"


async def test_backdating_is_allowed(env):
    """A driver collects at the gate at 11:00 and the office types it in at 18:00.

    The collection report has to follow the first, so `paidAt` is what the merchant says it is.
    """
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(
        env, token, invoice, 100, "CASH", paidAt="2026-09-01T05:30:00.000Z"
    )

    assert response.status_code == 201, response.text
    assert response.json()["paidAt"].startswith("2026-09-01")


async def test_an_unknown_invoice_is_a_404(env):
    token, _merchant, _customer, _invoice = await billed(env)

    response = await env.post(
        PAYMENTS, token, {"invoiceId": "does-not-exist", "amount": 100, "mode": "CASH"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "INVOICE_NOT_FOUND"


# --- Who may do it ---------------------------------------------------------------------------


async def test_reading_the_books_does_not_let_you_write_to_them(env):
    """`payments.view` is the accountant looking; `payments.collect` is them taking money."""
    token, _merchant, _customer, invoice = await billed(env, permissions=READ_ONLY)

    response = await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    assert response.status_code == 403


async def test_one_merchant_never_sees_another_s_invoice(env):
    """Ids are guessable, so the answer is 404 - a 403 would confirm it exists."""
    _token_a, _m_a, _c_a, invoice_a = await billed(env)
    token_b, _m_b, _c_b, _invoice_b = await billed(env)

    detail = await env.get(f"/api/v1/merchant/invoices/{invoice_a['id']}", token_b)
    paying = await pay(env, token_b, invoice_a, 100, "CASH")

    assert detail.status_code == 404
    assert paying.status_code == 404


# --- Concurrency -----------------------------------------------------------------------------


async def test_two_collections_at_once_cannot_overpay_the_invoice(env):
    """The invoice is locked for the duration of a collection.

    Without the lock both requests read the old balance, both pass the "not more than the
    balance" check, and the customer ends up having paid twice with no record of the credit.
    """
    token, _merchant, _customer, invoice = await billed(env)
    total = invoice["totalAmount"]

    first, second = await asyncio.gather(
        pay(env, token, invoice, total, "CASH"),
        pay(env, token, invoice, total, "CASH"),
        return_exceptions=True,
    )
    statuses = sorted(
        r.status_code for r in (first, second) if not isinstance(r, BaseException)
    )

    after = await invoice_now(env, token, invoice["id"])
    assert after["paidAmount"] == total, f"invoice overpaid: {after}"
    assert after["balance"] == 0
    # Exactly one may succeed; the other is refused for the balance or the settled invoice.
    assert 201 in statuses
    assert statuses.count(201) == 1


async def test_the_recorded_payment_count_matches_the_invoice(env):
    """The stored summary and the rows behind it are checked against each other directly."""
    token, _merchant, _customer, invoice = await billed(env)
    total = invoice["totalAmount"]
    await pay(env, token, invoice, total // 4, "CASH")
    await pay(env, token, await invoice_now(env, token, invoice["id"]), total // 4, "CASH")

    summed = await env.scalar(
        select(func.coalesce(func.sum(Payment.amount_collected), 0)).where(
            Payment.invoice_id == invoice["id"],
            Payment.reconciliation_status != ReconciliationStatus.INVALID.value,
        )
    )
    after = await invoice_now(env, token, invoice["id"])

    assert after["paidAmount"] == summed
    assert after["balance"] == after["totalAmount"] - after["paidAmount"]


# --- The actor -------------------------------------------------------------------------------


async def test_the_collector_is_taken_from_the_session(env):
    """Never from the body - a receipt has to say who actually took the money."""
    token, _merchant, _customer, invoice = await billed(env)

    response = await pay(env, token, invoice, 100, "CASH")

    assert response.json()["collectedBy"]
