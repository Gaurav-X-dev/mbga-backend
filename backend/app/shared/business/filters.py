"""Validated query-parameter filters shared by list endpoints.

List screens differ by filter, not by route: the same ``GET /orders`` serves "today",
"this month" and "cancelled" through these parameters rather than three endpoints.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import status

from app.shared.exceptions.api_error import ApiError

# A single list request may not sweep more than a year, which keeps report and list
# queries bounded without the caller having to page through silently truncated results.
MAX_RANGE_DAYS = 366

#: A four-digit year and a two-digit month, and nothing else.
_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


@dataclass(frozen=True)
class DateRange:
    """A closed date range as half-open UTC datetimes, ready for a SQL ``>=`` / ``<``."""

    start: date
    end: date

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time(), tzinfo=UTC)

    @property
    def end_at(self) -> datetime:
        """Exclusive upper bound, so the whole of `end` is included."""
        return datetime.combine(self.end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def validate_date_range(
    start: date | None,
    end: date | None,
    *,
    start_field: str = "from_date",
    end_field: str = "to_date",
    max_days: int = MAX_RANGE_DAYS,
) -> DateRange | None:
    """Return a validated range, or None when neither bound was supplied."""
    if start is None and end is None:
        return None
    if start is None or end is None:
        missing = start_field if start is None else end_field
        raise _invalid(missing, "date_range_incomplete", "Give both a start and an end date.")
    if end < start:
        raise _invalid(end_field, "date_range_reversed", "The end date cannot be before the start date.")
    if (end - start).days + 1 > max_days:
        raise _invalid(end_field, "date_range_too_wide", f"Choose a range of at most {max_days} days.")
    return DateRange(start=start, end=end)


def validate_month(value: str | None, *, field: str = "month") -> str | None:
    """Validate a ``YYYY-MM`` period (spec §1: ``reportPeriod`` / ``month``).

    The shape is checked before the parse. Parsing alone is not enough: ``26-09`` is a
    perfectly good ``date(26, 9, 1)``, so a two-digit year would be accepted and then match
    no stored period, returning an empty list that reads as "no activity this month".
    """
    if value is None:
        return None
    if not _MONTH_PATTERN.match(value):
        raise _invalid(field, "month_invalid", "Use the format YYYY-MM.")
    try:
        # A calendar month label, not an instant, so it is parsed to a date deliberately.
        _parse_month(value)
    except ValueError as exc:
        raise _invalid(field, "month_invalid", "Use the format YYYY-MM.") from exc
    return value


def _parse_month(value: str) -> date:
    year, _, month = value.partition("-")
    return date(int(year), int(month), 1)


def month_range(value: str) -> DateRange:
    """The first and last calendar day of a validated ``YYYY-MM`` month."""
    first = _parse_month(value)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return DateRange(start=first, end=next_month - timedelta(days=1))
