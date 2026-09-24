"""Keeping a merchant's current pricing month in existence.

The spec has no "create a pricing month" endpoint: the Standard tab expects the current
month to be there, and the mid-month endpoint 404s on a month that is not. Something has to
open each month, so it happens here, on the read and write paths, idempotently.

Two rules, both the ordinary behaviour of a monthly rate card:

* **Roll forward.** A new month opens with the previous month's rates. A merchant does not
  re-enter five rates on the 1st to carry on selling at yesterday's price; they change the
  ones that moved, through the mid-month endpoint, which logs them like any other change.
  The very first month a merchant ever has opens from `DEFAULT_STANDARD_RATES`.
* **Close the past.** A month whose last day has gone is ARCHIVED, which is what makes it
  read-only (a 409 from the write path). Nothing else archives a month.

Opening a month is not a price change, so it writes no `pricing_change_logs` row - the log
records what staff changed, and a carried-forward rate is the same rate.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing import calendar as cal
from app.modules.pricing.constants import (
    ACTIVE_TIER,
    DEFAULT_GST_PERCENT,
    DEFAULT_STANDARD_RATES,
    PricingMonthStatus,
)
from app.modules.pricing.models import PricingEntry, PricingMonth

#: Written into `updated_by` for a month nobody has edited yet.
SYSTEM_ACTOR = "System"


class PricingMonthProvisioner:
    """Opens the current month and archives finished ones, for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: str, merchant_code: str | None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.merchant_code = merchant_code

    async def ensure_current(self) -> PricingMonth:
        """Return this merchant's month for today, creating it if it does not exist.

        The caller commits. Concurrent first-touches of the same month race on the
        `(merchant_id, month)` unique constraint rather than producing two months.
        """
        today = cal.business_today()
        await self._archive_finished(today)
        current = await self.session.scalar(
            select(PricingMonth).where(
                PricingMonth.merchant_id == self.merchant_id,
                PricingMonth.month == cal.month_key(today),
            )
        )
        if current is not None:
            return current
        return await self._open(today)

    async def _archive_finished(self, today) -> None:
        stale = await self.session.scalars(
            select(PricingMonth).where(
                PricingMonth.merchant_id == self.merchant_id,
                PricingMonth.effective_to < today,
                PricingMonth.status != PricingMonthStatus.ARCHIVED.value,
            )
        )
        for month in stale:
            month.status = PricingMonthStatus.ARCHIVED.value

    async def _open(self, today):
        first, last = cal.month_bounds(today)
        now = datetime.now(UTC)
        previous = await self._latest_before(cal.month_key(today))
        month = PricingMonth(
            id=cal.month_id(self.merchant_code, today),
            merchant_id=self.merchant_id,
            month=cal.month_key(today),
            label=cal.month_label(today),
            effective_from=first,
            effective_to=last,
            status=PricingMonthStatus.ACTIVE.value,
            gst_percent=previous.gst_percent if previous else DEFAULT_GST_PERCENT,
            updated_by=previous.updated_by if previous else SYSTEM_ACTOR,
            updated_at=now,
        )
        self.session.add(month)
        # Flushed before its entries: the two are linked by a foreign key but by no ORM
        # relationship, so the unit of work does not order the inserts for us and the
        # entries would hit the constraint before their month exists.
        await self.session.flush()
        for cylinder_type, tier, base_rate, markup in await self._opening_rates(previous):
            self.session.add(
                PricingEntry(
                    pricing_month_id=month.id,
                    cylinder_type=cylinder_type,
                    tier=tier,
                    bpcl_base_rate=base_rate,
                    tier_markup=markup,
                )
            )
        await self.session.flush()
        return month

    async def _latest_before(self, month_key: str) -> PricingMonth | None:
        return await self.session.scalar(
            select(PricingMonth)
            .where(PricingMonth.merchant_id == self.merchant_id, PricingMonth.month < month_key)
            .order_by(PricingMonth.month.desc())
            .limit(1)
        )

    async def _opening_rates(self, previous: PricingMonth | None) -> list[tuple[str, str, Decimal, Decimal]]:
        """Last month's rates, or the default card when this merchant has no history.

        Every tier is carried forward, not only STANDARD, so switching Preferred or Key
        Account back on does not lose the rates they were last sold at.
        """
        if previous is None:
            return _default_card()
        entries = await self.session.scalars(
            select(PricingEntry).where(PricingEntry.pricing_month_id == previous.id)
        )
        carried = [
            (entry.cylinder_type, entry.tier, entry.bpcl_base_rate, entry.tier_markup) for entry in entries
        ]
        # A month that somehow has no entries still opens with a usable card rather than an
        # empty tab the screen cannot price anything from.
        return carried or _default_card()


def _default_card() -> list[tuple[str, str, Decimal, Decimal]]:
    """The opening STANDARD card for a merchant with no pricing history."""
    return [
        (kind.value, ACTIVE_TIER.value, base, markup)
        for kind, (base, markup) in DEFAULT_STANDARD_RATES.items()
    ]
