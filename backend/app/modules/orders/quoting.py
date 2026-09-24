"""Pricing a basket (spec §6.3, §18.1).

This is the one place an order learns what it costs, and it does **not** read the price card
itself. It asks `pricing.resolve_customer_price`, which is the same helper the Price Setting
tab and the customer's own pricing view call - so a per-customer override applies to the
quote, to the order, and to the invoice, or to none of them. Two code paths reading
`pricing_entries` directly is exactly how a screen and a bill end up disagreeing.

GST is broken **out of** the total, never added on top (spec §1, §18.1). The arithmetic is
`app.shared.money.gst.order_total`, which totals the lines first and splits once on the
final figure - splitting per line and summing the rounded parts does not reconcile.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.constants import ORDER_LABELS, SUMMARY_LABELS
from app.modules.pricing.constants import CylinderType
from app.modules.pricing.months import PricingMonthProvisioner
from app.modules.pricing.service import resolve_customer_price, tier_prices_for_month
from app.shared.exceptions.api_error import ApiError
from app.shared.money.gst import order_total


@dataclass(frozen=True)
class QuotedLine:
    cylinder_type: CylinderType
    label: str
    quantity: int
    unit_price: int
    line_total: int
    # True when the customer's own override set the price rather than the tier card.
    overridden: bool


@dataclass(frozen=True)
class Quote:
    lines: list[QuotedLine]
    total_cylinders: int
    total_amount: int
    subtotal: int
    gst_amount: int
    gst_percent: int
    pricing_month_id: str

    @property
    def items_summary(self) -> str:
        """`"6 × 47.5 L · 2 × 47.5 V"` (spec §3.10). Display only."""
        return " · ".join(
            f"{line.quantity} × {SUMMARY_LABELS[line.cylinder_type]}" for line in self.lines
        )


class QuoteEngine:
    """Prices a validated basket for one customer."""

    def __init__(self, session: AsyncSession, merchant_id: str, merchant_code: str | None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.merchant_code = merchant_code

    async def price(self, customer_id: str, lines: list[tuple[CylinderType, int]]) -> Quote:
        """Price each line, then total the order once.

        The basket is expected to be merged and range-checked already; this raises only for
        prices it cannot find, which is a configuration problem rather than a user error.
        """
        month = await PricingMonthProvisioner(
            self.session, self.merchant_id, self.merchant_code
        ).ensure_current()
        await self.session.commit()

        tier_prices = await tier_prices_for_month(self.session, month.id, "STANDARD")

        quoted: list[QuotedLine] = []
        for cylinder_type, quantity in lines:
            tier_price = tier_prices.get(cylinder_type.value)
            resolved = await resolve_customer_price(
                self.session, customer_id, cylinder_type.value, tier_price
            )
            if resolved is None:
                raise _not_priced(cylinder_type)
            unit_price = _whole_rupees(resolved)
            if unit_price <= 0:
                raise _not_priced(cylinder_type)
            quoted.append(
                QuotedLine(
                    cylinder_type=cylinder_type,
                    label=ORDER_LABELS[cylinder_type],
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=unit_price * quantity,
                    overridden=tier_price is None or resolved != tier_price,
                )
            )

        gst_percent = int(month.gst_percent)
        split = order_total([(line.unit_price, line.quantity) for line in quoted], gst_percent)
        return Quote(
            lines=quoted,
            total_cylinders=sum(line.quantity for line in quoted),
            total_amount=split.total_amount,
            subtotal=split.subtotal,
            gst_amount=split.gst_amount,
            gst_percent=split.gst_percent,
            pricing_month_id=month.id,
        )


def _whole_rupees(amount: Decimal) -> int:
    """Pricing carries paise; an order does not (spec §1 "Money").

    The rounding happens once, here at the boundary, and the rounded figure is what is
    stored on the line - so the number the customer was quoted is the number they are
    billed, with no second rounding anywhere downstream.
    """
    return int(Decimal(amount).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _not_priced(cylinder_type: CylinderType) -> ApiError:
    """No usable price for this type in the active month.

    A 409 rather than a 422: the basket the customer sent is legal, it is the merchant's
    price card that is incomplete, and only staff can fix it.
    """
    return ApiError(
        "CYLINDER_NOT_PRICED",
        status.HTTP_409_CONFLICT,
        f"{ORDER_LABELS[cylinder_type]} has no price set for this month. Contact the merchant.",
    )
