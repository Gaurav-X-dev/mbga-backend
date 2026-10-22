"""The rules for collecting money, tested without a database.

These are the checks that decide whether a merchant's books can be wrong. They run in
milliseconds here, which is why the edge cases - the rupee either side of a boundary, the
clock a few minutes fast - are worth spelling out one by one.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.payments import validation
from app.modules.payments.constants import InvoiceStatus, PaymentMode
from app.modules.payments.models import Invoice
from app.shared.exceptions.api_error import ApiError

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


def invoice(total: int = 1000, paid: int = 0) -> Invoice:
    return Invoice(
        total_amount=total,
        paid_amount=paid,
        balance=total - paid,
        status=InvoiceStatus.PAID.value if total == paid else InvoiceStatus.UNPAID.value,
        invoice_number="MBGA/INV/0001",
    )


def field_of(error: ApiError) -> str:
    return error.detail["fields"][0]["field"]


# --- Amount ----------------------------------------------------------------------------------


def test_the_whole_balance_is_allowed():
    assert validation.check_amount(1000, invoice(1000)) == 1000


def test_one_rupee_over_the_balance_is_not():
    """The boundary, because this is the check that stops a customer overpaying."""
    with pytest.raises(ApiError) as caught:
        validation.check_amount(1001, invoice(1000))

    assert field_of(caught.value) == "amount"
    assert caught.value.detail["fields"][0]["message"] == "Exceeds balance"


def test_the_remaining_balance_after_a_part_payment_is_what_counts():
    part_paid = invoice(1000, paid=400)

    assert validation.check_amount(600, part_paid) == 600
    with pytest.raises(ApiError):
        validation.check_amount(601, part_paid)


@pytest.mark.parametrize("amount", [0, -1, -1000])
def test_zero_or_negative_is_refused(amount):
    with pytest.raises(ApiError) as caught:
        validation.check_amount(amount, invoice(1000))

    assert caught.value.detail["fields"][0]["message"] == "Enter a valid amount"


def test_an_absurd_amount_is_refused_as_a_typo():
    """The common fat-finger is an extra zero, and it is caught before the balance check."""
    with pytest.raises(ApiError):
        validation.check_amount(100_000_000, invoice(200_000_000))


# --- Reference -------------------------------------------------------------------------------


def test_cash_needs_no_reference():
    assert validation.check_reference(PaymentMode.CASH, None) is None


@pytest.mark.parametrize("mode", [PaymentMode.UPI, PaymentMode.NEFT])
def test_a_bank_payment_needs_one(mode):
    with pytest.raises(ApiError) as caught:
        validation.check_reference(mode, None)

    assert field_of(caught.value) == "reference"


@pytest.mark.parametrize("mode", [PaymentMode.UPI, PaymentMode.NEFT])
def test_whitespace_is_not_a_reference(mode):
    """A space bar pressed to get past the field is the same as leaving it empty."""
    with pytest.raises(ApiError):
        validation.check_reference(mode, "   ")


def test_a_reference_is_trimmed():
    assert validation.check_reference(PaymentMode.UPI, "  UTR-123 ") == "UTR-123"


# --- paidAt ----------------------------------------------------------------------------------


def test_no_time_given_means_now():
    assert validation.check_paid_at(None, now=NOW) == NOW


def test_backdating_is_allowed():
    """A driver collects at the gate hours before the office types it in."""
    yesterday = NOW - timedelta(days=1)

    assert validation.check_paid_at(yesterday, now=NOW) == yesterday


def test_a_naive_timestamp_is_read_as_utc():
    """MySQL keeps no offset, so anything that comes back naive has to be pinned down."""
    naive = datetime(2026, 9, 28, 9, 0)  # noqa: DTZ001 - naive on purpose, that is the case

    assert validation.check_paid_at(naive, now=NOW).tzinfo is not None


def test_a_slightly_fast_clock_is_tolerated():
    """A handset a couple of minutes ahead must not refuse a real collection."""
    assert validation.check_paid_at(NOW + timedelta(minutes=2), now=NOW)


def test_tomorrow_is_refused():
    with pytest.raises(ApiError) as caught:
        validation.check_paid_at(NOW + timedelta(days=1), now=NOW)

    assert field_of(caught.value) == "paidAt"


# --- Invoice state ---------------------------------------------------------------------------


def test_an_open_invoice_passes():
    assert validation.check_open(invoice(1000)) is not None


def test_a_settled_invoice_is_refused():
    with pytest.raises(ApiError) as caught:
        validation.check_open(invoice(1000, paid=1000))

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "INVOICE_ALREADY_PAID"


# --- Reconciliation --------------------------------------------------------------------------


def test_confirming_a_payment_needs_no_reason():
    assert validation.check_reason(True, None) is None


def test_rejecting_one_does():
    """Somebody is about to be told they still owe. That deserves a note."""
    with pytest.raises(ApiError) as caught:
        validation.check_reason(False, None)

    assert field_of(caught.value) == "reason"


def test_a_rejection_reason_is_trimmed():
    assert validation.check_reason(False, "  UTR not found  ") == "UTR not found"
