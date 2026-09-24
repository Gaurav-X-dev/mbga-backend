"""Field checks for the expense writes.

Every failure is the project's coded `VALIDATION_ERROR` envelope naming the offending field,
so the Add-expense sheet can highlight the one input that is wrong instead of showing a
generic toast.

These run in the service rather than as Pydantic constraints on purpose: a Pydantic failure
on a merchant route comes back in FastAPI's list shape, which the web panel maps to form
fields, while the mobile contract wants `detail.fields[].field`. One shape, decided here.
"""

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import status

from app.modules.expenses.constants import (
    MAX_BACKDATE_DAYS,
    MAX_CODE_LENGTH,
    MAX_EXPENSE_AMOUNT,
    MAX_LABEL_LENGTH,
    MAX_NOTE_LENGTH,
    ExpenseIcon,
)
from app.shared.exceptions.api_error import ApiError

_PAISE = Decimal("0.01")
# A category code is a machine key the app may send back in a filter, so it is kept to
# characters that survive a URL and a query string untouched.
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def amount(value: Decimal | None, *, field: str = "amount") -> Decimal:
    """Return the amount rounded to paise, or raise a 422 naming `field`.

    Rejects zero and negatives (an expense is money going out, and a refund is not modelled
    here), anything that is not a finite number, and figures too large to be anything but a
    typed-in extra zero. Rounding happens here so the number the operator is told was saved
    is the number the column holds - MySQL would drop a third decimal silently.
    """
    if value is None:
        raise invalid(field, "required", "Enter an amount.")
    try:
        money = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise invalid(field, "amount_not_a_number", "Enter a valid amount.") from error
    # NaN and Infinity survive Decimal(); they must not survive this.
    if not money.is_finite():
        raise invalid(field, "amount_not_a_number", "Enter a valid amount.")
    money = money.quantize(_PAISE, rounding=ROUND_HALF_UP)
    if money <= 0:
        raise invalid(field, "amount_not_positive", "Amount must be more than zero.")
    if money > MAX_EXPENSE_AMOUNT:
        raise invalid(field, "amount_too_large", "Amount is too large. Check for an extra zero.")
    return money


def spent_on(value: date | None, *, today: date, field: str = "date") -> date:
    """Default an omitted date to today, and bound it at both ends.

    Back-dating is allowed - bills arrive late and books get caught up - but a future date
    is refused, because money that has not been spent yet is not an expense. The far bound
    catches a mistyped year, which would otherwise file the row into a report period nobody
    ever opens.
    """
    if value is None:
        return today
    if value > today:
        raise invalid(field, "date_in_future", "The date cannot be in the future.")
    if value < today - timedelta(days=MAX_BACKDATE_DAYS):
        raise invalid(field, "date_too_old", "That date is too far in the past. Check the year.")
    return value


def note(value: str | None, *, field: str = "note") -> str | None:
    """Trim the note; blank becomes null so the list renders nothing rather than a gap."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_NOTE_LENGTH:
        raise invalid(field, "note_too_long", f"Keep the note under {MAX_NOTE_LENGTH} characters.")
    return text


def label(value: str | None, *, field: str = "label") -> str:
    """A category's display name. Required, trimmed, bounded."""
    text = (value or "").strip()
    if not text:
        raise invalid(field, "required", "Enter a category name.")
    if len(text) > MAX_LABEL_LENGTH:
        raise invalid(field, "label_too_long", f"Keep the name under {MAX_LABEL_LENGTH} characters.")
    return text


def category_code(value: str | None, *, fallback: str, field: str = "code") -> str:
    """A category's machine key, derived from the name when the caller sends none.

    The app's Add-category form has one text box, so the code is almost always generated:
    "Godown Repairs" becomes `GODOWN_REPAIRS`. A caller that does send one must send
    something that survives a URL unescaped, because it comes back as a filter value.
    """
    text = (value or "").strip().upper()
    if not text:
        text = _slug(fallback)
    if not text:
        raise invalid(field, "required", "Enter a category name.")
    if len(text) > MAX_CODE_LENGTH:
        raise invalid(field, "code_too_long", f"Keep the code under {MAX_CODE_LENGTH} characters.")
    if not _CODE_PATTERN.match(text):
        raise invalid(
            field,
            "code_invalid",
            "Use capital letters, digits and underscores only, starting with a letter.",
        )
    return text


def _slug(text: str) -> str:
    """'Godown Repairs' -> 'GODOWN_REPAIRS'."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_").upper()
    # A code has to start with a letter; a name beginning with a digit gets a prefix
    # rather than being rejected, since the operator only typed a name.
    if cleaned and cleaned[0].isdigit():
        cleaned = f"C_{cleaned}"
    return cleaned[:MAX_CODE_LENGTH]


def icon(value: str | None, *, field: str = "icon") -> str:
    """Restrict icons to the keys the app can actually draw."""
    if value is None:
        return ExpenseIcon.MISC.value
    text = str(value).strip().lower()
    try:
        return ExpenseIcon(text).value
    except ValueError as error:
        allowed = ", ".join(member.value for member in ExpenseIcon)
        raise invalid(field, "icon_unknown", f"Use one of {allowed}.") from error
