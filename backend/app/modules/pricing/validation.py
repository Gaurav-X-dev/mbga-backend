"""Amount and date checks for the pricing writes.

Every failure is the project's coded `VALIDATION_ERROR` envelope naming the offending field,
which is the shape the spec's error contract maps to `VALIDATION`.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import status

from app.shared.exceptions.api_error import ApiError

#: The largest value a DECIMAL(10,2) column holds. A bigger number is a typo, not a price.
MAX_PRICE = Decimal("99999999.99")
_CENTS = Decimal("0.01")


def _invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def money(value: Decimal | None, *, field: str, allow_zero: bool = False) -> Decimal:
    """Return `value` rounded to paise, or raise a 422 naming `field`.

    Rounding here rather than at the column keeps the number the operator is told was saved
    identical to the number the database holds - MySQL would round a third decimal silently.
    """
    if value is None:
        raise _invalid(field, "required", "Enter an amount.")
    try:
        amount = Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise _invalid(field, "money_not_a_number", "Enter a valid amount.") from error
    if not amount.is_finite():
        raise _invalid(field, "money_not_a_number", "Enter a valid amount.")
    if amount < 0:
        raise _invalid(field, "money_negative", "Amount cannot be negative.")
    if amount == 0 and not allow_zero:
        raise _invalid(field, "money_zero", "Amount must be more than zero.")
    if amount > MAX_PRICE:
        raise _invalid(field, "money_too_large", "Amount is too large.")
    return amount


def effective_from(value: date | None, *, today: date, field: str = "effectiveFrom") -> date:
    """Default an omitted date to today, and refuse a date already in the past.

    Spec: `effectiveFrom` records when a change takes effect; there is no backdating of
    history, and holding a future price before it is live is out of scope - so a future date
    is accepted and recorded, but a past one is not.
    """
    if value is None:
        return today
    if value < today:
        raise _invalid(field, "date_in_past", "The effective date cannot be before today.")
    return value
