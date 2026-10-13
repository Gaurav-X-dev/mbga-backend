"""Request and response models for the delivery app (API_REFERENCE)."""

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.modules.deliveries.constants import (
    CANCELLATION_REASON_LABELS,
    REASONS_REQUIRING_NOTES,
    CancellationReason,
)
from app.modules.payments.constants import MAX_PAYMENT_AMOUNT

UPI_ID_PATTERN = r"^[a-zA-Z0-9._-]{2,}@[a-zA-Z][a-zA-Z0-9._-]{1,}$"

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)

T = TypeVar("T")


class BaseResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    model_config = _CAMEL


class SuccessWrapperResponse(BaseResponse[Any]):
    pass


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[
    datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")
]


# --- Deliveries ------------------------------------------------------------------------------


class CustomerLocation(BaseModel):
    id: str
    name: str
    phone: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    is_location_captured: bool = Field(alias="isLocationCaptured", default=False)
    model_config = _CAMEL


class CustomerInfoDetail(BaseModel):
    name: str
    phone: str
    address: str
    model_config = _CAMEL


class DeliveryItemResponse(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    label: str
    quantity: int
    unit_price: float | None = Field(default=None, alias="unitPrice")
    total_price: float | None = Field(default=None, alias="totalPrice")
    model_config = _CAMEL


class EmptyReturnItem(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    label: str
    current_order_quantity: int = Field(alias="currentOrderQuantity")
    customer_previous_due: int = Field(alias="customerPreviousDue")
    expected_quantity: int = Field(alias="expectedQuantity")
    model_config = _CAMEL


class BillingSummary(BaseModel):
    """The money panel on the driver's delivery screen, read top to bottom.

    `orderSubtotal` + `taxAmount` = `grandTotal`, and `grandTotal` + `customerPreviousBalance`
    = `totalPayableAmount`. Both sums hold exactly, so the screen can print the arithmetic and
    a customer can follow it at the gate.
    """

    #: This delivery **without** GST. It used to be the sum of the line totals, which is the
    #: GST-inclusive figure - so it equalled the grand total and the tax line read as though it
    #: were being added on top.
    order_subtotal: float = Field(alias="orderSubtotal")
    #: The GST contained in this delivery, broken out of the total rather than added to it.
    tax_amount: float = Field(alias="taxAmount")
    #: `orderSubtotal + taxAmount`. What this delivery alone comes to.
    grand_total: float = Field(alias="grandTotal")
    #: What the customer owed before today, across their other open invoices.
    customer_previous_balance: float = Field(alias="customerPreviousBalance")
    #: `grandTotal + customerPreviousBalance` - everything the customer owes once this delivery
    #: is handed over, which is the figure the driver asks for.
    total_payable_amount: float = Field(alias="totalPayableAmount")
    model_config = _CAMEL


class DriverDeliveryResponse(BaseModel):
    """Step 1: GET /deliveries/today"""

    id: str
    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    status: str
    delivery_date: str = Field(alias="deliveryDate")
    customer: CustomerLocation
    distance_km: float | None = Field(default=None, alias="distanceKm")
    items: list[DeliveryItemResponse]
    empty_returns: list[EmptyReturnItem] = Field(alias="emptyReturns")
    billing: BillingSummary
    model_config = _CAMEL


class OutForDeliveryResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    status: str
    updated_at: str = Field(alias="updatedAt")
    dev_confirmation_code: str | None = Field(default=None, alias="devConfirmationCode")
    model_config = _CAMEL


class CancelDeliveryRequest(BaseModel):
    """Close a delivery that did not happen.

    No OTP. The commonest reason a run fails is that the customer was not there - the shop was
    shut, nobody came to the gate - and asking that customer for a code to record it would make
    the one case this exists for the one case it cannot handle. The driver is accountable by the
    reason they type, which goes on the slip and into the trail.
    """

    #: Why, from the list at `GET /cancellation-reasons`. Optional, so an app that has always
    #: sent free text keeps working.
    reason_code: CancellationReason | None = Field(default=None, alias="reasonCode")
    #: What goes on the slip and into the order's trail. Built from the code when one is sent
    #: and nothing is typed, so the reason is never blank.
    reason: str | None = Field(default=None, max_length=500)
    #: The driver's own words. Required when the code says nothing on its own - see `OTHER`.
    driver_notes: str | None = Field(default=None, alias="driverNotes", max_length=500)
    model_config = _CAMEL

    @model_validator(mode="after")
    def check_reason(self):
        """A cancelled delivery nobody can account for afterwards is the thing this prevents."""
        if self.reason_code in REASONS_REQUIRING_NOTES and not (self.driver_notes or "").strip():
            raise ValueError("driverNotes is required for this reason")
        if self.reason_code is None and not (self.reason or "").strip():
            raise ValueError("reason or reasonCode is required")
        return self

    @property
    def stated_reason(self) -> str:
        """One line for the slip, the order's trail and the customer's notification."""
        typed = (self.reason or "").strip()
        if typed:
            return typed
        label = CANCELLATION_REASON_LABELS[self.reason_code]
        notes = (self.driver_notes or "").strip()
        return f"{label} - {notes}" if notes else label


class CancellationReasonOption(BaseModel):
    """One row of the driver app's cancellation dropdown."""

    code: str
    label: str
    #: True when the code says nothing on its own and the driver must write something.
    requires_notes: bool = Field(alias="requiresNotes")
    sort_order: int = Field(alias="sortOrder")
    model_config = _CAMEL


class CancellationReasonsResponseData(BaseModel):
    items: list[CancellationReasonOption]


class CancelDeliveryResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    delivery_status: str = Field(alias="deliveryStatus")
    order_status: str = Field(alias="orderStatus")
    cancelled_at: str = Field(alias="cancelledAt")
    model_config = _CAMEL


class VerifyLocationRequest(BaseModel):
    latitude: float
    longitude: float
    model_config = _CAMEL


class VerifyLocationResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    delivery_status: str = Field(alias="deliveryStatus")
    order_status: str = Field(alias="orderStatus")
    arrived_at: UtcTime = Field(alias="arrivedAt")
    is_at_location: bool = Field(alias="isAtLocation")
    distance_meters_from_destination: float | None = Field(
        alias="distanceMetersFromDestination", default=None
    )
    is_location_captured: bool = Field(alias="isLocationCaptured")
    message: str
    model_config = _CAMEL


class UpdateItemEntry(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    quantity: int
    model_config = _CAMEL


class UpdateItemsRequest(BaseModel):
    updated_items: list[UpdateItemEntry] = Field(alias="updatedItems")
    reason: str
    model_config = _CAMEL


class AvailableCylinderTypeItem(BaseModel):
    """One customer-eligible cylinder offered in the doorstep order sheet."""

    cylinder_type: str = Field(alias="cylinderType")
    label: str
    unit_price: float = Field(alias="unitPrice")
    model_config = _CAMEL


class AvailableCylinderTypesResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    customer_type: str = Field(alias="customerType")
    cylinder_types: list[AvailableCylinderTypeItem] = Field(alias="cylinderTypes")
    model_config = _CAMEL


class GenerateQrRequest(BaseModel):
    """What to put in the UPI link.

    `orderId` is optional: the delivery is already named in the path and it knows its own order,
    so making the app repeat it only adds a value it can get wrong - an order *number* instead of
    an id, say. Sent, it is still checked, because an app confused about which delivery it is on
    is worth catching.
    """

    order_id: str | None = Field(default=None, alias="orderId", max_length=36)
    amount: float = Field(gt=0, le=MAX_PAYMENT_AMOUNT, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=200)
    model_config = _CAMEL

    @field_validator("order_id", mode="before")
    @classmethod
    def trim_required_text(cls, value: str | None) -> str | None:
        trimmed = value.strip() if isinstance(value, str) else value
        return trimmed or None

    @field_validator("notes", mode="before")
    @classmethod
    def trim_optional_notes(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        return value.strip() or None


class GenerateQrResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    amount: float
    upi_id: str = Field(alias="upiId")
    payee_name: str = Field(alias="payeeName")
    notes: str | None = None
    upi_string: str = Field(alias="upiString")
    qr_code_base64: str = Field(alias="qrCodeBase64")
    mime_type: str = Field(default="image/png", alias="mimeType")
    model_config = _CAMEL


class CollectedEmptyEntry(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    quantity: int
    model_config = _CAMEL


class DeliveredItemEntry(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    quantity: int
    model_config = _CAMEL


class PaymentEntry(BaseModel):
    """What the driver collected at the gate, as the Delivery App states it.

    `payableAmount` and `pendingBalance` are the app's own arithmetic and are read for nothing:
    both are worked out from the order and the money banked against it, and taking the app's
    word for either would let a stale screen decide what a customer owes. Only `method`,
    `amountCollected` and the evidence are acted on.
    """

    method: str
    split: str
    amount_collected: float = Field(alias="amountCollected")
    payable_amount: float = Field(alias="payableAmount")
    pending_balance: float = Field(alias="pendingBalance")
    #: UTR or UPI transaction id. **Optional**, unlike the merchant panel's own form: the UTR
    #: appears on the customer's phone, not the driver's, so demanding it would make UPI
    #: uncollectable at the gate. Sending it makes the payment easier to reconcile later.
    reference: str | None = Field(default=None, max_length=80)
    #: How the collection was split, on the way **back**. Absent on the request.
    #:
    #: A driver may be handed the arrears along with today's bill, and the money is then applied
    #: to several invoices - this delivery first, then the older ones, oldest first. Without
    #: these the receipt could only show this delivery's invoice, which made a collection of
    #: 1,819 read as 1,390 and the rest look dropped.
    applied_to_this_delivery: float | None = Field(
        default=None, alias="appliedToThisDelivery"
    )
    applied_to_previous_due: float | None = Field(
        default=None, alias="appliedToPreviousDue"
    )
    model_config = _CAMEL


class ConfirmDeliveryRequest(BaseModel):
    delivered_items: list[DeliveredItemEntry] = Field(alias="deliveredItems")
    collected_empties: list[CollectedEmptyEntry] = Field(alias="collectedEmpties")
    #: Optional, so a slip can be confirmed with the money following later.
    payment: PaymentEntry | None = None
    driver_notes: str | None = Field(alias="driverNotes", default=None)
    model_config = _CAMEL


class ConfirmDeliveryResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    customer_otp_required: bool = Field(alias="customerOtpRequired")
    otp_channel: str = Field(alias="otpChannel")
    message: str
    model_config = _CAMEL


class VerifyCustomerOtpRequest(BaseModel):
    otp: str
    model_config = _CAMEL


class EmptyDueSummary(BaseModel):
    expected_total: int = Field(alias="expectedTotal")
    collected_total: int = Field(alias="collectedTotal")
    added_to_customer_pending_due: int = Field(alias="addedToCustomerPendingDue")
    model_config = _CAMEL


class VerifyCustomerOtpResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    status: str
    completed_at: str = Field(alias="completedAt")
    total_delivered_quantity: int = Field(alias="totalDeliveredQuantity")
    delivered_items: list[DeliveryItemResponse] = Field(alias="deliveredItems")
    total_empty_collected_quantity: int = Field(alias="totalEmptyCollectedQuantity")
    empty_collected_items: list[DeliveryItemResponse] = Field(alias="emptyCollectedItems")
    empty_due_summary: EmptyDueSummary = Field(alias="emptyDueSummary")
    payment: PaymentEntry | dict[str, Any] = Field(default_factory=dict)
    model_config = _CAMEL


class CompletedDeliveryDetailResponseData(BaseModel):
    id: str
    order_number: str = Field(alias="orderNumber")
    status: str
    delivery_date: str = Field(alias="deliveryDate")
    completed_at: str = Field(alias="completedAt")
    customer: CustomerInfoDetail
    delivered_items: list[DeliveryItemResponse] = Field(alias="deliveredItems")
    empty_items: list[DeliveryItemResponse] = Field(alias="emptyItems")
    payment: dict[str, Any] = Field(default_factory=dict)
    driver_notes: str | None = Field(alias="driverNotes", default=None)
    model_config = _CAMEL


class HistoryPaymentSummary(BaseModel):
    method: str
    amount: float
    status: str
    model_config = _CAMEL


class HistoryDeliveryEntry(BaseModel):
    id: str
    order_number: str = Field(alias="orderNumber")
    customer_name: str = Field(alias="customerName")
    status: str
    delivery_date: str = Field(alias="deliveryDate")
    completed_at: str | None = Field(alias="completedAt", default=None)
    total_delivered_count: int = Field(alias="totalDeliveredCount")
    total_empties_count: int = Field(alias="totalEmptiesCount")
    items_summary: str = Field(alias="itemsSummary")
    payment: HistoryPaymentSummary | dict[str, Any] = Field(default_factory=dict)
    model_config = _CAMEL


class HistoryDeliveriesResponseData(BaseModel):
    items: list[HistoryDeliveryEntry]
    total: int
    page: int
    limit: int
    model_config = _CAMEL


# --- Driver Profile ---------------------------------------------------------


class ShiftStats(BaseModel):
    completed_deliveries_today: int = Field(alias="completedDeliveriesToday")
    total_completed_deliveries: int = Field(alias="totalCompletedDeliveries")
    cash_collected_today: float = Field(alias="cashCollectedToday")
    total_empties_collected_today: int = Field(alias="totalEmptiesCollectedToday")
    model_config = _CAMEL


class DriverProfileResponseData(BaseModel):
    id: str
    name: str
    phone: str
    vehicle_number: str | None = Field(default=None, alias="vehicleNumber")
    role: str
    on_duty: bool = Field(alias="onDuty")
    avatar_initials: str | None = Field(default=None, alias="avatarInitials")
    shift_stats: ShiftStats | None = Field(default=None, alias="shiftStats")
    model_config = _CAMEL


class UpdateDutyRequest(BaseModel):
    on_duty: bool = Field(alias="onDuty")
    model_config = _CAMEL


class DriverInventoryLine(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    label: str
    full_count: int = Field(alias="fullCount")
    empty_count: int = Field(alias="emptyCount")
    model_config = _CAMEL


class DriverInventoryResponseData(BaseModel):
    total_full_cylinders: int = Field(alias="totalFullCylinders")
    total_empty_cylinders: int = Field(alias="totalEmptyCylinders")
    active_deliveries_count: int = Field(alias="activeDeliveriesCount")
    stock_by_type: list[DriverInventoryLine] = Field(alias="stockByType")
    model_config = _CAMEL


class DaySummaryLine(BaseModel):
    """One cylinder size on the driver's own day."""

    cylinder_type: str = Field(alias="cylinderType")
    label: str
    #: Cylinders of this size actually handed over today, not what the van set out with.
    delivered: int
    #: Shells of this size taken back today, whichever visit they were owed from.
    empties_collected: int = Field(alias="emptiesCollected")
    model_config = _CAMEL


class DaySummaryResponseData(BaseModel):
    """What this driver has done today, in totals and size by size.

    The totals and the lines are the same numbers read two ways: `totalDelivered` is the sum of
    every line's `delivered`, and `totalEmptiesCollected` of every `emptiesCollected`. The
    screen can print the arithmetic and it will add up.

    **Completed work only.** A delivery still on the van has not happened yet; counting it
    would have the driver hand in a figure the godown cannot match against anything.
    """

    #: The business day these numbers are for, as the cut-off decides it (`YYYY-MM-DD`).
    date: str
    deliveries_completed: int = Field(alias="deliveriesCompleted")
    total_delivered: int = Field(alias="totalDelivered")
    total_empties_collected: int = Field(alias="totalEmptiesCollected")
    by_type: list[DaySummaryLine] = Field(alias="byType")
    model_config = _CAMEL


class OutForDeliveryBulkRequest(BaseModel):
    """The deliveries the driver is setting off with.

    Capped at fifty: a van carries a round, not a day's book, and an unbounded list is how one
    request locks every slip a merchant has.
    """

    delivery_ids: list[str] = Field(alias="deliveryIds", min_length=1, max_length=50)
    model_config = _CAMEL


class PaymentSummaryResponseData(BaseModel):
    """What the payment screen needs, in one call.

    Three figures that have to agree on one screen - this delivery, what was owed before, and
    what a QR may be raised for - so they are worked out together rather than each coming from
    a different request at a different moment.
    """

    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    customer_name: str | None = Field(default=None, alias="customerName")
    #: This delivery, GST inside. After the handover it is what the invoice bills; before it,
    #: what the order comes to.
    delivery_amount: float = Field(alias="deliveryAmount")
    amount_paid: float = Field(alias="amountPaid")
    pending_amount: float = Field(alias="pendingAmount")
    #: Open balances on this customer's **other** invoices, so the two can be added without
    #: counting this delivery twice.
    customer_previous_due: float = Field(alias="customerPreviousDue")
    total_due: float = Field(alias="totalDue")
    #: The ceiling the QR endpoint and the confirmation both enforce: `totalDue`. The driver
    #: is at the gate and can be handed the arrears as well, and whatever he collects above
    #: this delivery's own bill is applied to the older invoices, oldest first.
    max_qr_amount: float = Field(alias="maxQrAmount")
    upi_available: bool = Field(alias="upiAvailable")
    upi_id: str | None = Field(default=None, alias="upiId")
    payee_name: str | None = Field(default=None, alias="payeeName")
    #: The last QR shown at this gate, if any - so a driver returning to the screen sees what
    #: he already asked for instead of raising a second one.
    last_qr_amount: float | None = Field(default=None, alias="lastQrAmount")
    last_qr_at: str | None = Field(default=None, alias="lastQrAt")
    #: What the driver may choose, from the platform's own list rather than the app's.
    modes: list[str]
    model_config = _CAMEL
