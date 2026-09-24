"""The 16:00 IST order cut-off (spec §6.2, §18.4).

Order before 16:00 IST -> delivered tomorrow 09:00, morning slot.
Order after            -> delivered the day after tomorrow, afternoon slot.

The whole rule is evaluated in IST because 16:00 is a time the operator and the customer
both read off a wall clock. Evaluating it in UTC would move the cut-off to 21:30 IST and
quietly promise next-day delivery for five and a half hours a day that the godown cannot
honour.

`scheduledDeliveryDate` goes out as a real UTC instant, not the wall-clock time with a `Z`
stapled on. 09:00 IST is `03:30Z`; sending `09:00Z` would make every app render it as
14:30 IST. The spec's demo payload takes the shortcut, the backend does not.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.shared.date_time.business_calendar import IST

#: Wall-clock cut-off, IST.
CUTOFF_HOUR = 16
CUTOFF_TIME = f"{CUTOFF_HOUR:02d}:00"

#: When the van arrives, IST.
MORNING_DELIVERY = time(9, 0)
AFTERNOON_DELIVERY = time(14, 0)

MORNING_SLOT = "09:00 AM – 01:00 PM"
AFTERNOON_SLOT = "02:00 PM – 06:00 PM"

WITHIN_MESSAGE = "Order before 4:00 PM for next-day delivery."
AFTER_MESSAGE = "Today's cut-off has passed. This order is scheduled for the day after tomorrow."


@dataclass(frozen=True)
class Cutoff:
    """The cut-off as it stood at one instant. Frozen onto the order at placement.

    Stored with the order rather than recomputed on read: a customer opening an order a week
    later must see the promise that was made when they placed it, not what the rule would
    say today.
    """

    cutoff_time: str
    within_cutoff: bool
    scheduled_delivery_date: datetime
    message: str
    delivery_slot: str


def evaluate(now: datetime | None = None) -> Cutoff:
    """Evaluate the cut-off for `now` (defaults to this instant)."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    local = moment + IST
    within = local.hour < CUTOFF_HOUR

    delivery_day = local.date() + timedelta(days=1 if within else 2)
    delivery_time = MORNING_DELIVERY if within else AFTERNOON_DELIVERY
    return Cutoff(
        cutoff_time=CUTOFF_TIME,
        within_cutoff=within,
        scheduled_delivery_date=_ist_to_utc(delivery_day, delivery_time),
        message=WITHIN_MESSAGE if within else AFTER_MESSAGE,
        delivery_slot=MORNING_SLOT if within else AFTERNOON_SLOT,
    )


def _ist_to_utc(day: date, at: time) -> datetime:
    """An IST wall-clock moment as a real UTC instant."""
    return (datetime.combine(day, at) - IST).replace(tzinfo=UTC)
