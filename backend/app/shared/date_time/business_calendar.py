"""Business dates: the calendar the people using the apps actually live in.

Pricing months, expense report periods and any user-entered date are **calendar dates in
India**, not instants. Deriving "today" from UTC puts the backend a day behind the operator
between 00:00 and 05:30 IST - long enough for a night-shift entry dated today to be rejected
as "in the future". So anything that compares a typed-in date against "now" comes here.

Stored timestamps (`created_at`, `changed_at`, ...) stay UTC like every other row in the
database. This module is about *dates*, not instants.
"""

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta

#: India Standard Time. A fixed offset - India has no daylight saving.
IST = timedelta(hours=5, minutes=30)

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def business_today() -> date:
    """The calendar date it is for the people using the app."""
    return (datetime.now(UTC) + IST).date()


def month_key(day: date) -> str:
    """'YYYY-MM' for the month `day` falls in."""
    return f"{day.year:04d}-{day.month:02d}"


def month_label(day: date) -> str:
    """'September 2026'."""
    return f"{MONTH_NAMES[day.month - 1]} {day.year}"


def month_key_label(period: str) -> str:
    """'September 2026' from a stored `YYYY-MM` string.

    Used by list responses, which hold the period as text rather than a date.
    """
    year, _, month = period.partition("-")
    try:
        return f"{MONTH_NAMES[int(month) - 1]} {int(year)}"
    except (ValueError, IndexError):
        # A row with an unparseable period still renders; it shows its raw value rather
        # than taking the whole list down.
        return period


def month_bounds(day: date) -> tuple[date, date]:
    """First and last day of `day`'s month."""
    last = monthrange(day.year, day.month)[1]
    return date(day.year, day.month, 1), date(day.year, day.month, last)
