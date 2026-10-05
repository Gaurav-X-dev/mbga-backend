"""The order cut-off (spec §6.2, §18.4).

Order before the cut-off, IST -> delivered the **same day**.
Order after                   -> delivered the next day.

The hour is `ORDER_CUTOFF_HOUR`, 16 by default. It is a setting rather than a constant because
it is an operating decision: a merchant who extends their day to 18:00 should need a line in
`.env` and a restart, not a release. Everything shown about the cut-off - the 24-hour string the
apps parse and the "Order before 4:00 PM" sentence a customer reads - is derived from that one
number, so the screens cannot promise an hour the godown is not working to.

The whole rule is evaluated in IST because the cut-off is a time the operator and the customer
both read off a wall clock. Evaluating it in UTC would move it five and a half hours later and
quietly promise same-day delivery for a stretch of each day the godown cannot honour.

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

from app.config.app import get_settings
from app.shared.date_time.business_calendar import IST

#: How many days after the order's own business day the van goes out. Inside the cut-off there is
#: still a working afternoon left, so the order goes today; after it, the next day.
DAYS_WITHIN = 0
DAYS_AFTER = 1

AFTER_MESSAGE = "Today's cut-off has passed. This order is scheduled for tomorrow."


def cutoff_hour() -> int:
    """The configured hour, IST. `ORDER_CUTOFF_HOUR` in the environment.

    Read per call rather than bound at import, so a deployment that changes it needs a restart
    and not a release. `get_settings()` is cached, so this is a dictionary lookup.
    """
    return get_settings().order_cutoff_hour


def clock_24h(hour: int) -> str:
    """`16` -> `"16:00"`. What the API publishes, because an app parses it."""
    return f"{hour:02d}:00"


def clock_12h(hour: int) -> str:
    """`16` -> `"4:00 PM"`. What a person reads, because the message is shown to a customer.

    Derived rather than written down beside the hour: the two drifting apart would mean a screen
    promising four o'clock while the godown worked to six, and nobody would see it until an order
    was refused for being late when the app said it was early.
    """
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display}:00 {suffix}"


def within_message(hour: int) -> str:
    return f"Order before {clock_12h(hour)} for same-day delivery."


@dataclass(frozen=True)
class Cutoff:
    """The cut-off as it stood at one instant. Frozen onto the order at placement.

    Stored with the order rather than recomputed on read: a customer opening an order a week
    later must see the promise that was made when they placed it, not what the rule would say
    today - and the rule itself can change, as it has.
    """

    cutoff_time: str
    within_cutoff: bool
    scheduled_delivery_date: date
    message: str


def evaluate(now: datetime | None = None, *, hour: int | None = None) -> Cutoff:
    """Evaluate the cut-off for `now` (defaults to this instant).

    `hour` overrides the configured one. Only tests pass it: everything in the application reads
    the setting, so there is one answer to "when is the cut-off" at any moment.
    """
    configured = cutoff_hour() if hour is None else hour
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    local = moment + IST
    # The business day, not the UTC one: an order placed at 00:30 IST is today's, not yesterday's.
    today = local.date()
    within = local.hour < configured

    return Cutoff(
        cutoff_time=clock_24h(configured),
        within_cutoff=within,
        scheduled_delivery_date=today + timedelta(days=DAYS_WITHIN if within else DAYS_AFTER),
        message=within_message(configured) if within else AFTER_MESSAGE,
    )
