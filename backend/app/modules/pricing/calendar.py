"""Pricing's view of the business calendar.

The IST date helpers moved to `app.shared.date_time.business_calendar` when expenses needed
the same "today"; they are re-exported here so pricing's call sites keep reading `cal.*`.
Only `month_id`, which is about pricing months specifically, lives here.
"""

from datetime import date

from app.shared.date_time.business_calendar import (  # noqa: F401
    IST,
    MONTH_NAMES,
    business_today,
    month_bounds,
    month_key,
    month_label,
)


def month_id(merchant_code: str | None, day: date) -> str:
    """A readable, stable id for one merchant's month, e.g. `PRC-MBGA-IND-01-2026-09`.

    The merchant code is part of it because each merchant prices independently; uniqueness
    is still enforced by the `(merchant_id, month)` constraint, not by this string.
    """
    code = (merchant_code or "").strip().upper()[:40]
    return f"PRC-{code}-{month_key(day)}" if code else f"PRC-{month_key(day)}"
