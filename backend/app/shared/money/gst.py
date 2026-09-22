"""GST-inclusive splitting and order/line totals.

Decimal is used for the division so the rounding is half-up and deterministic, rather than
Python's banker's rounding on floats: ``round(2.5)`` is 2 but ``₹2.50`` of GST must become
``₹3``. Every value entering and leaving these helpers is an ``int`` of whole rupees.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.shared.money.validation import validate_money, validate_quantity

# Spec §18.1. Pricing records may carry an approved rate; callers pass it explicitly.
DEFAULT_GST_PERCENT = 18


@dataclass(frozen=True)
class GstSplit:
    """A total broken into its taxable value and the GST already inside it."""

    total_amount: int
    subtotal: int
    gst_amount: int
    gst_percent: int

    def __post_init__(self) -> None:
        # The identity the invoice and every report depend on.
        if self.subtotal + self.gst_amount != self.total_amount:
            raise ValueError("GST split does not reconcile to the total")


class _Line(NamedTuple):
    unit_price: int
    quantity: int


def split_gst(total_amount: int, gst_percent: int = DEFAULT_GST_PERCENT) -> GstSplit:
    """Extract the GST already contained in `total_amount`.

    ``subtotal = round(total / (1 + pct/100))`` and ``gst = total - subtotal``, so the two
    parts always add back to the total exactly — the remainder lands in the GST, never lost.
    """
    validate_money(total_amount, field="total_amount")
    if isinstance(gst_percent, bool) or not isinstance(gst_percent, int) or not 0 <= gst_percent <= 100:
        raise ValueError("gst_percent must be an integer between 0 and 100")
    divisor = Decimal(100 + gst_percent) / Decimal(100)
    subtotal = int((Decimal(total_amount) / divisor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return GstSplit(
        total_amount=total_amount,
        subtotal=subtotal,
        gst_amount=total_amount - subtotal,
        gst_percent=gst_percent,
    )


def line_total(unit_price: int, quantity: int, *, field_prefix: str = "items") -> int:
    """GST-inclusive total for one order line."""
    validate_money(unit_price, field=f"{field_prefix}.unit_price", allow_zero=False)
    validate_quantity(quantity, field=f"{field_prefix}.quantity")
    total = unit_price * quantity
    return validate_money(total, field=f"{field_prefix}.line_total")


def order_total(lines: list[tuple[int, int]], gst_percent: int = DEFAULT_GST_PERCENT) -> GstSplit:
    """Total an order's lines, then split the GST **once** on the final figure.

    Passing the lines rather than a pre-computed total is deliberate: it keeps callers from
    splitting GST per line and summing the rounded parts, which does not reconcile.
    """
    if not lines:
        raise ValueError("An order needs at least one line")
    total = 0
    for index, (unit_price, quantity) in enumerate(_Line(*line) for line in lines):
        total += line_total(unit_price, quantity, field_prefix=f"items.{index}")
    validate_money(total, field="total_amount", allow_zero=False)
    return split_gst(total, gst_percent)


def invoice_gst(total_amount: int, gst_percent: int = DEFAULT_GST_PERCENT) -> GstSplit:
    """The only supported way to split an invoice or report figure.

    Named separately from `split_gst` so the call site reads as a deliberate choice to
    derive GST from a final total, which is what spec §18.1 requires.
    """
    return split_gst(total_amount, gst_percent)
