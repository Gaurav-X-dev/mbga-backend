"""Integer whole-rupee money and GST-inclusive arithmetic.

API_SPEC 1.md §1 and §18.1: every amount the platform stores and returns is an integer
number of whole rupees, and every price already includes GST. GST is therefore always
*extracted* from a total, never added on top:

    total_amount = sum(unit_price * quantity)
    subtotal     = round(total_amount / (1 + gst_percent / 100))
    gst_amount   = total_amount - subtotal

The division is lossy, so a subtotal is only ever derived from a *final* total. Summing
independently rounded line subtotals drifts from the invoice total; `invoice_gst` is the
only supported way to split an invoice or report figure.
"""

from app.shared.money.gst import (
    DEFAULT_GST_PERCENT,
    GstSplit,
    invoice_gst,
    line_total,
    order_total,
    split_gst,
)
from app.shared.money.validation import (
    MAX_MONEY,
    MAX_QUANTITY,
    validate_money,
    validate_quantity,
)

__all__ = [
    "DEFAULT_GST_PERCENT",
    "MAX_MONEY",
    "MAX_QUANTITY",
    "GstSplit",
    "invoice_gst",
    "line_total",
    "order_total",
    "split_gst",
    "validate_money",
    "validate_quantity",
]
