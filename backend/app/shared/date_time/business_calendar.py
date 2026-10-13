"""Business dates: the calendar the people using the apps actually live in.

Pricing months, expense report periods and any user-entered date are **calendar dates in
India**, not instants. Deriving "today" from UTC puts the backend a day behind the operator
between 00:00 and 05:30 IST - long enough for a night-shift entry dated today to be rejected
as "in the future". So anything that compares a typed-in date against "now" comes here.

Stored timestamps (`created_at`, `changed_at`, ...) stay UTC like every other row in the
database. This module is about *dates*, not instants.
"""

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta, timezone

#: India Standard Time. A fixed offset - India has no daylight saving.
IST = timedelta(hours=5, minutes=30)
IST_TIMEZONE = timezone(IST, name="Asia/Kolkata")

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


def financial_year(day: date) -> str:
    """`'26-27'` for the Indian financial year `day` falls in.

    April to March, which is what every invoice book in the country runs on. A delivery on
    31 March and one on 1 April belong to different years and must not share a number series -
    which is the whole reason the year is printed on the invoice.

    Two digits each side, as it is written on a bill by hand and as the agency asked for it.
    The century is not printed and does not need to be: an invoice book is read in its own
    time, and the merchant and the number together already say which year is meant.
    """
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def business_day_window(day: date) -> tuple[datetime, datetime]:
    """The UTC half-open range `[start, end)` covering one IST calendar day.

    For counting what somebody actually did on a day. MySQL `DATETIME` holds no offset, so a
    timestamp comes back naive UTC; comparing it against an IST date needs the day's own
    boundaries translated once, here, rather than a `CONVERT_TZ` on every row - which would
    also stop the index being used.

    Returned naive, to match what the ORM hands back from those columns.
    """
    start = datetime.combine(day, time.min, tzinfo=IST_TIMEZONE)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        (start + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None),
    )
