"""Bounds checks for money and quantity inputs, raising the project error envelope."""

from fastapi import status

from app.shared.exceptions.api_error import ApiError

# A single amount the platform will accept, in whole rupees. Well inside MySQL BIGINT and
# far above any realistic LPG order, so it catches typos and overflow probes rather than
# constraining the business.
MAX_MONEY = 10_000_000_000
# Cylinders on one order line. Per-type limits are tighter (spec §18.3); this is the
# absolute ceiling that stops a quantity from overflowing a total.
MAX_QUANTITY = 100_000


def _invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def validate_money(value: object, *, field: str = "amount", allow_zero: bool = True) -> int:
    """Return `value` as whole rupees, or raise a 422 naming `field`.

    Rejects bools (``True`` is an ``int`` in Python), floats, and anything outside
    ``0..MAX_MONEY`` — money never arrives as a fraction because the platform has no paise.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field, "money_not_integer", "Enter a whole rupee amount.")
    if value < 0:
        raise _invalid(field, "money_negative", "Amount cannot be negative.")
    if value == 0 and not allow_zero:
        raise _invalid(field, "money_zero", "Amount must be more than zero.")
    if value > MAX_MONEY:
        raise _invalid(field, "money_too_large", "Amount is too large.")
    return value


def validate_quantity(value: object, *, field: str = "quantity", minimum: int = 1, maximum: int | None = None) -> int:
    """Return `value` as a positive count, or raise a 422 naming `field`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field, "quantity_not_integer", "Enter a whole number.")
    ceiling = MAX_QUANTITY if maximum is None else min(maximum, MAX_QUANTITY)
    if value < minimum or value > ceiling:
        raise _invalid(field, "quantity_out_of_range", f"Enter a quantity between {minimum} and {ceiling}.")
    return value
