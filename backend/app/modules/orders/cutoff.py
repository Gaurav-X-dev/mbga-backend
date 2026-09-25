"""The 16:00 IST order cut-off (spec §6.2, §18.4).

Order before 16:00 IST -> delivered tomorrow.
Order after            -> delivered the day after tomorrow.

The whole rule is evaluated in IST because 16:00 is a time the operator and the customer both
read off a wall clock. Evaluating it in UTC would move the cut-off to 21:30 IST and quietly
promise next-day delivery for five and a half hours a day that the godown cannot honour.

**There is no delivery slot.** The platform used to promise a morning or afternoon window
("09:00 AM – 01:00 PM") derived from which side of the cut-off an order landed. It was removed:
the godown routes a van by what is on it and where it is going, not by what an app told a
customer at 5pm the day before, and a window nobody schedules against is a promise that gets
broken. What is promised now is the **day**, which is the part the merchant actually commits to.

`scheduledDeliveryDate` is therefore a plain calendar date - `"2026-09-26"` - and not an instant.
That is deliberate: a delivery day has no time of day, and sending it as a timestamp is what made
it renderable five and a half hours out in the first place.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.shared.date_time.business_calendar import IST

#: Wall-clock cut-off, IST.
CUTOFF_HOUR = 16
CUTOFF_TIME = f"{CUTOFF_HOUR:02d}:00"

WITHIN_MESSAGE = "Order before 4:00 PM for next-day delivery."
AFTER_MESSAGE = "Today's cut-off has passed. This order is scheduled for the day after tomorrow."


@dataclass(frozen=True)
class Cutoff:
    """The cut-off as it stood at one instant. Frozen onto the order at placement.

    Stored with the order rather than recomputed on read: a customer opening an order a week
    later must see the promise that was made when they placed it, not what the rule would say
    today - and the rule itself can change.
    """

    cutoff_time: str
    within_cutoff: bool
    scheduled_delivery_date: date
    message: str


def evaluate(now: datetime | None = None) -> Cutoff:
    """Evaluate the cut-off for `now` (defaults to this instant)."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    # The business day, not the UTC one: an order placed at 00:30 IST is today's, not yesterday's.
    local = (moment + IST).date()
    within = (moment + IST).hour < CUTOFF_HOUR

    return Cutoff(
        cutoff_time=CUTOFF_TIME,
        within_cutoff=within,
        scheduled_delivery_date=local + timedelta(days=1 if within else 2),
        message=WITHIN_MESSAGE if within else AFTER_MESSAGE,
    )
