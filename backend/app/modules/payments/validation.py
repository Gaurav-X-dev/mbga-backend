"""Field and state rules for recording a payment (spec §12.5).

Every failure is the coded `VALIDATION_ERROR` envelope with `detail.fields[].field` naming the
input to fix, and the messages are the spec's own wording - "Enter a valid amount", "Exceeds
balance", "Reference is required" - because the app shows them verbatim under the field.

These live here rather than in the service so that "what may be collected" reads in one place
and can be tested without a database.
"""

from datetime import UTC, datetime, timedelta

from fastapi import status as http_status

from app.modules.payments.constants import (
    MAX_PAYMENT_AMOUNT,
    REFERENCE_REQUIRED_MODES,
    InvoiceStatus,
    PaymentMode,
)
from app.modules.payments.models import Invoice
from app.shared.exceptions.api_error import ApiError

INVALID_AMOUNT_MESSAGE = "Enter a valid amount"
EXCEEDS_BALANCE_MESSAGE = "Exceeds balance"
REFERENCE_REQUIRED_MESSAGE = "Reference is required"

#: How far in the future a `paidAt` may sit. Small, and there only to absorb a handset whose
#: clock is a few minutes fast - money cannot be collected tomorrow.
FUTURE_TOLERANCE = timedelta(minutes=5)


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def check_amount(amount: int, invoice: Invoice) -> int:
    """The amount collected, or a field error naming what is wrong.

    Over-collection is refused rather than held as credit. The platform has no customer wallet,
    so an amount above the balance would be money with nowhere to sit - and the merchant taking
    it would have no record of owing it back.
    """
    if amount <= 0 or amount > MAX_PAYMENT_AMOUNT:
        raise invalid("amount", "invalid_amount", INVALID_AMOUNT_MESSAGE)
    if amount > invoice.balance:
        raise invalid("amount", "exceeds_balance", EXCEEDS_BALANCE_MESSAGE)
    return amount


def check_reference(mode: PaymentMode, reference: str | None) -> str | None:
    """A bank reference, required for anything but cash.

    Without it a UPI or NEFT payment can never be matched against a statement, which leaves it
    `PENDING` for ever - recorded, uncollectable and permanently in the way.
    """
    cleaned = (reference or "").strip() or None
    if mode in REFERENCE_REQUIRED_MODES and not cleaned:
        raise invalid("reference", "reference_required", REFERENCE_REQUIRED_MESSAGE)
    return cleaned


def check_paid_at(paid_at: datetime | None, *, now: datetime) -> datetime:
    """When the money changed hands. Defaults to now; may be backdated, never postdated.

    Backdating is ordinary and necessary: a driver collects cash at the gate at 11:00 and the
    office types it in at 18:00, and the collection report has to follow the first. Postdating
    is not - it would put money in a report before it exists.
    """
    if paid_at is None:
        return now
    moment = paid_at if paid_at.tzinfo else paid_at.replace(tzinfo=UTC)
    if moment > now + FUTURE_TOLERANCE:
        raise invalid("paidAt", "future_payment", "A payment cannot be dated in the future")
    return moment


def check_open(invoice: Invoice) -> Invoice:
    """The invoice must still owe something (spec §12.5: "Must be open")."""
    if invoice.balance <= 0 or invoice.status == InvoiceStatus.PAID.value:
        raise ApiError(
            "INVOICE_ALREADY_PAID",
            http_status.HTTP_409_CONFLICT,
            f"Invoice {invoice.invoice_number} is already settled in full.",
        )
    return invoice


def check_reason(reconciled: bool, reason: str | None) -> str | None:
    """A rejected payment must say why.

    Marking money invalid puts a balance back onto a customer who believes they have paid. The
    person who has to make that call deserves to find a reason written down rather than a
    status that changed one afternoon.
    """
    cleaned = (reason or "").strip() or None
    if not reconciled and not cleaned:
        raise invalid("reason", "reason_required", "Say why this payment could not be matched")
    return cleaned
