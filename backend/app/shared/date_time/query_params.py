"""A `from`/`to` query parameter that takes a date or a timestamp.

`from` and `to` mean a **date** on the expenses and pricing screens and a **timestamp** on the
reports screen. One parameter name, two types, and nothing on the wire says which - so an app
that sends `from=2026-10-04T13:37:00Z` to all three gets a report and two refusals:

    query.from: Datetimes provided to dates should have zero time - e.g. be exact dates

That message is correct and completely unhelpful to the person reading it, who picked
"Last 7 days" on a phone.

The date is the answer either way - an expense happened on a day, a price took effect on a day
- so this takes whichever form the caller sends and reduces it to that day.

**An offset is read in IST.** `2026-10-04T18:40:00Z` is twenty past midnight on the 5th in
Delhi, and the person choosing it was looking at an Indian calendar. Taking the UTC date would
put their spend in the wrong day at both ends of every range. A timestamp with no offset is
taken as it reads, because that is what a client that omitted one meant.
"""

from datetime import date, datetime
from typing import Annotated

from pydantic import BeforeValidator

from app.shared.date_time.business_calendar import IST_TIMEZONE


def as_business_date(value: object) -> object:
    """Reduce a date, a timestamp or a string of either to the business day it names."""
    if isinstance(value, datetime):
        return _day_of(value)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            # `fromisoformat` takes both `2026-10-04` and `2026-10-04T13:37:00+05:30`; a `Z`
            # suffix is spelled `+00:00` for it.
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            # Not ISO at all. Handed on untouched so the field's own error is reported rather
            # than one from here, which would name a type the caller never mentioned.
            return value
        return _day_of(parsed) if "T" in text or " " in text else parsed.date()
    return value


def _day_of(moment: datetime) -> date:
    """The IST calendar day a timestamp falls on."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(IST_TIMEZONE).date()


#: Use in place of `date` on a query parameter a client might send a timestamp for.
BusinessDate = Annotated[date, BeforeValidator(as_business_date)]
