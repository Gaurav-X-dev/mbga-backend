"""Request and response models for the order screens (spec §3.8-3.11, §6).

Field names are the mobile contract's camelCase. Amounts are plain integers - spec §1 fixes
Money as whole rupees - so no Decimal serializer is needed here, unlike pricing and expenses.

Timestamps go out as UTC with a `Z`, because MySQL DATETIME keeps no offset and a naive
string is read by JS as local time, which would show every order placed five and a half
hours out.

Ranges are checked in `validation.py` so a bad field comes back in the coded envelope the
apps read, rather than FastAPI's list-shaped 422.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.customers.business_schemas import Address
from app.modules.orders.constants import OrderMode, OrderSource, OrderStatus, StatusTone
from app.modules.pricing.constants import CylinderType

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- Catalogue and cut-off ------------------------------------------------------------------


class OrderStatusMetaResponse(BaseModel):
    """Spec §3.11. The app builds its timeline from this and hard-codes nothing."""

    code: OrderStatus
    label: str
    sequence: int
    tone: StatusTone
    description: str
    is_terminal: bool = Field(alias="isTerminal")

    model_config = _CAMEL


class CutoffResponse(BaseModel):
    """Spec §3.8."""

    cutoff_time: str = Field(alias="cutoffTime")
    within_cutoff: bool = Field(alias="withinCutoff")
    #: A plain date - `"2026-09-26"`. There is no delivery slot; see `orders/cutoff.py`.
    scheduled_delivery_date: date = Field(alias="scheduledDeliveryDate")
    # Rendered verbatim to the user.
    message: str

    model_config = _CAMEL


# --- Lines ----------------------------------------------------------------------------------


class OrderLineRequest(BaseModel):
    """One requested line. Quantity limits are per cylinder type (spec §18.3)."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    quantity: int

    model_config = _CAMEL


class OrderItemResponse(BaseModel):
    """Spec §3.9. `unitPrice` is GST-inclusive, per cylinder."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    quantity: int
    unit_price: int = Field(alias="unitPrice")
    line_total: int = Field(alias="lineTotal")

    model_config = _CAMEL


# --- Quote ------------------------------------------------------------------------------------


class OrderQuoteRequest(BaseModel):
    customer_id: str = Field(alias="customerId")
    items: list[OrderLineRequest] = Field(default_factory=list)

    model_config = _CAMEL


class OrderQuoteResponse(BaseModel):
    """Spec §6.3. GST is broken **out of** the total, never added on top."""

    items: list[OrderItemResponse] = Field(default_factory=list)
    total_cylinders: int = Field(alias="totalCylinders")
    total_amount: int = Field(alias="totalAmount")
    gst_percent: int = Field(alias="gstPercent")
    subtotal: int
    gst_amount: int = Field(alias="gstAmount")
    cutoff: CutoffResponse

    model_config = _CAMEL


# --- Order --------------------------------------------------------------------------------------


class OrderStatusEntry(BaseModel):
    """One step of the tracking timeline. Oldest first."""

    status: OrderStatus
    at: UtcTime
    by: str | None = None
    note: str | None = None

    model_config = _CAMEL


class OrderResponse(BaseModel):
    """Spec §3.10."""

    id: str
    order_number: str = Field(alias="orderNumber")
    customer_id: str = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")
    customer_type: str = Field(alias="customerType")
    items: list[OrderItemResponse] = Field(default_factory=list)
    total_cylinders: int = Field(alias="totalCylinders")
    # Display only - "6 × 47.5 L · 2 × 47.5 V".
    items_summary: str = Field(alias="itemsSummary")
    order_mode: OrderMode = Field(alias="orderMode")
    source: OrderSource
    delivery_site_id: str | None = Field(default=None, alias="deliverySiteId")
    delivery_site_name: str = Field(alias="deliverySiteName")
    delivery_address: Address = Field(alias="deliveryAddress")
    subtotal: int
    gst_percent: int = Field(alias="gstPercent")
    gst_amount: int = Field(alias="gstAmount")
    total_amount: int = Field(alias="totalAmount")
    status: OrderStatus
    status_history: list[OrderStatusEntry] = Field(default_factory=list, alias="statusHistory")
    placed_at: UtcTime = Field(alias="placedAt")
    # The cut-off as evaluated at placement, not as it would be evaluated now.
    cutoff: CutoffResponse
    created_by: str | None = Field(default=None, alias="createdBy")
    delivery_slip_id: str | None = Field(default=None, alias="deliverySlipId")
    invoice_id: str | None = Field(default=None, alias="invoiceId")

    model_config = _CAMEL


class CreateOrderRequest(BaseModel):
    """Spec §6.4.

    `source` is optional here although the spec marks it required: the backend already knows
    which app is calling from the session's channel, and §1 says an actor field must never
    be trusted from the client. A value that disagrees with the channel is refused rather
    than silently believed.
    """

    customer_id: str = Field(alias="customerId")
    items: list[OrderLineRequest] = Field(default_factory=list)
    order_mode: OrderMode = Field(default=OrderMode.NEW, alias="orderMode")
    delivery_site_id: str | None = Field(default=None, alias="deliverySiteId")
    source: OrderSource | None = None

    model_config = _CAMEL


class CancelOrderRequest(BaseModel):
    """Beyond the spec's six endpoints - see the note on the cancel route."""

    reason: str | None = Field(default=None, max_length=255)

    model_config = _CAMEL


# --- Reorder ---------------------------------------------------------------------------------


class UnavailableLine(BaseModel):
    """A line from the source order that cannot be repeated today, and why.

    The reason is a sentence the app shows verbatim, because the user has to decide what to
    do about it - drop the line, or call the merchant.
    """

    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    quantity: int
    reason: str

    model_config = _CAMEL


class ReorderPreviewResponse(BaseModel):
    """What repeating this order would cost and change, before anything is placed.

    A reorder is one tap, so the confirm sheet has to be able to say "this is ₹200 more than
    last time" and "the 422 Hippo is no longer available" *before* the order exists. Placing
    first and explaining afterwards would mean cancelling to undo it.
    """

    source_order_id: str = Field(alias="sourceOrderId")
    source_order_number: str = Field(alias="sourceOrderNumber")
    # So the sheet can head itself "Last order · 12 Sep · Delivered" without a second call.
    source_order_status: OrderStatus = Field(alias="sourceOrderStatus")
    source_placed_at: UtcTime = Field(alias="sourcePlacedAt")
    source_items_summary: str = Field(alias="sourceItemsSummary")
    # Priced at today's card, never copied from the source order.
    items: list[OrderItemResponse] = Field(default_factory=list)
    total_cylinders: int = Field(alias="totalCylinders")
    total_amount: int = Field(alias="totalAmount")
    gst_percent: int = Field(alias="gstPercent")
    subtotal: int
    gst_amount: int = Field(alias="gstAmount")
    cutoff: CutoffResponse
    # What the source order cost, so the sheet can show the difference.
    previous_total_amount: int = Field(alias="previousTotalAmount")
    price_changed: bool = Field(alias="priceChanged")
    # Lines that cannot be repeated. When this is non-empty `canReorder` is false and the
    # app must let the user edit the basket instead.
    unavailable: list[UnavailableLine] = Field(default_factory=list)
    can_reorder: bool = Field(alias="canReorder")
    # Why not, when `canReorder` is false and it is not about a line - a suspended account,
    # a delivery site that no longer exists.
    blocked_reason: str | None = Field(default=None, alias="blockedReason")
    delivery_site_id: str | None = Field(default=None, alias="deliverySiteId")
    delivery_site_name: str = Field(alias="deliverySiteName")

    model_config = _CAMEL


class ReorderRequest(BaseModel):
    """Overrides for a repeat order. Everything is optional - the plain case sends no body.

    `items` is the escape hatch: when the preview reports a line that can no longer be
    repeated, the app sends the adjusted basket here rather than forcing the user back
    through the full Create Order screen.
    """

    items: list[OrderLineRequest] | None = None
    delivery_site_id: str | None = Field(default=None, alias="deliverySiteId")

    model_config = _CAMEL


class RepeatOrderRequest(BaseModel):
    """Repeat a customer's last order, without the app having to know its id.

    `customerId` is how staff repeat for a customer they are looking at; a customer's own
    app omits it and the session decides. `items` and `deliverySiteId` are the same
    overrides `ReorderRequest` carries, for when the preview reported a line that can no
    longer be repeated.
    """

    customer_id: str | None = Field(default=None, alias="customerId")
    items: list[OrderLineRequest] | None = None
    delivery_site_id: str | None = Field(default=None, alias="deliverySiteId")

    model_config = _CAMEL
