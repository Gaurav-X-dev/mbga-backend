"""Settling a pending payment against the bank statement.

The consequential half is marking one invalid: money the customer believes they have paid stops
counting, and their balance comes back. So the reason is required, the row is kept rather than
deleted, and the office is told.
"""

import pytest
from sqlalchemy import select

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


async def _pending(env, token, invoice, amount=None):
    """A UPI payment waiting for a bank match."""
    response = await pay(
        env, token, invoice, amount or invoice["totalAmount"], "UPI", reference="UPI-4471820039"
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_matched_payment_becomes_reconciled(env):
    token, _merchant, _customer, invoice = await billed(env)
    payment = await _pending(env, token, invoice)

    response = await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile", token, {"reconciled": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["reconciliationStatus"] == ReconciliationStatus.RECONCILED.value
    assert response.json()["invalidReason"] is None
    # Money that was always there does not move.
    assert (await invoice_now(env, token, invoice["id"]))["balance"] == 0


async def test_an_unmatched_payment_puts_the_balance_back(env):
    """The customer believes they have paid. They have not, and the books have to say so."""
    token, _merchant, _customer, invoice = await billed(env)
    payment = await _pending(env, token, invoice)
    assert (await invoice_now(env, token, invoice["id"]))["balance"] == 0

    response = await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile",
        token,
        {"reconciled": False, "reason": "UTR not found in bank statement"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["reconciliationStatus"] == ReconciliationStatus.INVALID.value
    assert response.json()["invalidReason"] == "UTR not found in bank statement"

    after = await invoice_now(env, token, invoice["id"])
    assert after["balance"] == invoice["totalAmount"]
    assert after["paidAmount"] == 0
    assert after["status"] == InvoiceStatus.UNPAID.value


async def test_an_invalid_payment_is_kept_not_deleted(env):
    """It is evidence that somebody recorded a collection that turned out to be wrong."""
    token, _merchant, _customer, invoice = await billed(env)
    payment = await _pending(env, token, invoice)
    await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile",
        token,
        {"reconciled": False, "reason": "UTR not found"},
    )

    row = await env.scalar(select(Payment).where(Payment.id == payment["id"]))

    assert row is not None
    assert row.amount_collected == invoice["totalAmount"]
    assert row.reconciled_by_name, "who made the call has to be on the row"


async def test_rejecting_without_a_reason_is_refused(env):
    """Somebody is about to be told they still owe. That deserves a note."""
    token, _merchant, _customer, invoice = await billed(env)
    payment = await _pending(env, token, invoice)

    response = await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile", token, {"reconciled": False}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "reason"
    # Nothing moved.
    assert (await invoice_now(env, token, invoice["id"]))["balance"] == 0


async def test_cash_is_already_settled_and_cannot_be_reconciled_again(env):
    token, _merchant, _customer, invoice = await billed(env)
    paid = await pay(env, token, invoice, invoice["totalAmount"], "CASH")

    response = await env.post(
        f"{PAYMENTS}/{paid.json()['id']}/reconcile", token, {"reconciled": True}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PAYMENT_ALREADY_RECONCILED"


async def test_a_payment_cannot_be_reconciled_twice(env):
    token, _merchant, _customer, invoice = await billed(env)
    payment = await _pending(env, token, invoice)
    await env.post(f"{PAYMENTS}/{payment['id']}/reconcile", token, {"reconciled": True})

    again = await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile",
        token,
        {"reconciled": False, "reason": "Changed my mind"},
    )

    assert again.status_code == 409
    # And the money did not move a second time.
    assert (await invoice_now(env, token, invoice["id"]))["balance"] == 0


async def test_reversing_a_part_payment_returns_only_that_part(env):
    token, _merchant, _customer, invoice = await billed(env)
    total = invoice["totalAmount"]
    await pay(env, token, invoice, total // 2, "CASH")
    pending = await _pending(
        env, token, await invoice_now(env, token, invoice["id"]), total - total // 2
    )

    await env.post(
        f"{PAYMENTS}/{pending['id']}/reconcile",
        token,
        {"reconciled": False, "reason": "UTR not found"},
    )

    after = await invoice_now(env, token, invoice["id"])
    assert after["paidAmount"] == total // 2
    assert after["balance"] == total - total // 2
    assert after["status"] == InvoiceStatus.PARTIAL.value


async def test_reconciling_needs_its_own_permission(env):
    """`payments.view` reads the books; `payments.reconcile` decides what is true in them."""
    token, _merchant, _customer, invoice = await billed(env, permissions=READ_ONLY)
    # READ_ONLY cannot record either, so the pending payment is made by staff who can.
    full_token, _m, _c, other_invoice = await billed(env)
    payment = await _pending(env, full_token, other_invoice)

    response = await env.post(
        f"{PAYMENTS}/{payment['id']}/reconcile", token, {"reconciled": True}
    )

    assert response.status_code in (403, 404)
    assert invoice["id"]


async def test_the_list_filters_on_reconciliation_state(env):
    token, _merchant, _customer, invoice = await billed(env)
    total = invoice["totalAmount"]
    await pay(env, token, invoice, total // 2, "CASH")
    await _pending(env, token, await invoice_now(env, token, invoice["id"]), total - total // 2)

    pending = await env.get(PAYMENTS, token, params={"reconciliationStatus": "PENDING"})
    reconciled = await env.get(PAYMENTS, token, params={"reconciliationStatus": "RECONCILED"})
    everything = await env.get(PAYMENTS, token, params={"reconciliationStatus": "ALL"})

    assert [row["mode"] for row in pending.json()] == ["UPI"]
    assert [row["mode"] for row in reconciled.json()] == ["CASH"]
    assert len(everything.json()) == 2


async def test_an_unknown_filter_value_is_refused(env):
    """Silently returning everything would look like "no such payments" to the accountant."""
    token, _merchant, _customer, _invoice = await billed(env)

    response = await env.get(PAYMENTS, token, params={"reconciliationStatus": "MAYBE"})

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "reconciliationStatus"
