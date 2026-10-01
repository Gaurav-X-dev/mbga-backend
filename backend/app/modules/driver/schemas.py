"""Request and response models for the delivery app (API_REFERENCE)."""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.driver.constants import MAX_NOTE_LENGTH, DriverDeliveryStatus

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

UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


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
    order_subtotal: float = Field(alias="orderSubtotal")
    tax_amount: float = Field(alias="taxAmount")
    customer_previous_balance: float = Field(alias="customerPreviousBalance")
    total_payable_amount: float = Field(alias="totalPayableAmount")
    model_config = _CAMEL

class DriverDeliveryResponse(BaseModel):
    """Step 1: GET /deliveries/today"""
    id: str
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
    model_config = _CAMEL


class VerifyLocationRequest(BaseModel):
    latitude: float
    longitude: float
    model_config = _CAMEL

class VerifyLocationResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    is_at_location: bool = Field(alias="isAtLocation")
    distance_meters_from_destination: float | None = Field(alias="distanceMetersFromDestination", default=None)
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

class GenerateQrRequest(BaseModel):
    amount: float
    payment_split: str = Field(alias="paymentSplit") # "full" | "partial"
    model_config = _CAMEL

class GenerateQrResponseData(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    amount: float
    upi_string: str = Field(alias="upiString")
    qr_image_url: str = Field(alias="qrImageUrl")
    expires_in_seconds: int = Field(alias="expiresInSeconds")
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
    method: str
    split: str
    amount_collected: float = Field(alias="amountCollected")
    payable_amount: float = Field(alias="payableAmount")
    pending_balance: float = Field(alias="pendingBalance")
    model_config = _CAMEL

class ConfirmDeliveryRequest(BaseModel):
    delivered_items: list[DeliveredItemEntry] = Field(alias="deliveredItems")
    collected_empties: list[CollectedEmptyEntry] = Field(alias="collectedEmpties")
    payment: PaymentEntry
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
