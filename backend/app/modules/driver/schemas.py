"""Request and response models for the delivery app (API_REFERENCE §6-§10).

These follow the delivery app's contract rather than the dispatch board's. Where the two
disagree the app wins, because it is already built and tested against these names - `orderNumber`
not `slipNumber`, lower-case statuses, a flat `address` string the driver can paste into maps.

What the app is **not** given: the slip's money, the crew, the merchant's stock. A driver needs
to know what to hand over and to whom.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.driver.constants import MAX_NOTE_LENGTH, DriverDeliveryStatus

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- Deliveries ------------------------------------------------------------------------------


class DeliveryItemResponse(BaseModel):
    """One cylinder type on the drop."""

    cylinder_type: str = Field(alias="cylinderType")
    label: str
    quantity: int

    model_config = _CAMEL


class DriverDeliveryResponse(BaseModel):
    """One delivery as the driver's app renders it (§6.1, §6.2)."""

    id: str
    order_number: str = Field(alias="orderNumber")
    slip_number: str = Field(alias="slipNumber")
    customer_name: str = Field(alias="customerName")
    customer_phone: str | None = Field(default=None, alias="customerPhone")
    #: One line, ready to show or hand to a maps app. The structured parts are on the order.
    address: str
    delivery_site_name: str = Field(alias="deliverySiteName")
    items: list[DeliveryItemResponse]
    items_summary: str = Field(alias="itemsSummary")
    cylinders_allocated: int = Field(alias="cylindersAllocated")
    status: DriverDeliveryStatus
    scheduled_date: date = Field(alias="scheduledDate")
    #: Null until the site has coordinates recorded and the driver has pressed Start.
    distance_km: float | None = Field(default=None, alias="distanceKm")
    started_at: UtcTime | None = Field(default=None, alias="startedAt")
    completed_at: UtcTime | None = Field(default=None, alias="completedAt")
    empties_collected: int = Field(alias="emptiesCollected")
    #: Whether this drop still needs the customer's code. False once it is delivered or failed.
    requires_customer_otp: bool = Field(alias="requiresCustomerOtp")

    model_config = _CAMEL


class StartDeliveryRequest(BaseModel):
    """Where the driver is when they set off (§7.1)."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    model_config = _CAMEL


class StartDeliveryResponse(BaseModel):
    """The answer to "am I there yet?".

    `isAtLocation` is a hint for the app's UI, not a gate. It is true whenever the distance
    cannot be measured, because a site with no recorded coordinates must not stop a driver who
    is standing in front of it.
    """

    delivery_id: str = Field(alias="deliveryId")
    is_at_location: bool = Field(alias="isAtLocation")
    distance_metres_from_destination: float | None = Field(
        default=None, alias="distanceMetersFromDestination"
    )
    status: DriverDeliveryStatus

    model_config = _CAMEL


class ConfirmDeliveryRequest(BaseModel):
    """What the driver counted at the gate (§7.2)."""

    delivered_quantity: int = Field(alias="deliveredQuantity", ge=0)
    empty_collected_quantity: int = Field(default=0, alias="emptyCollectedQuantity", ge=0)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    model_config = _CAMEL


class ConfirmDeliveryResponse(BaseModel):
    """Counts are recorded; the handover is not final until the code is verified."""

    delivery_id: str = Field(alias="deliveryId")
    customer_otp_required: bool = Field(alias="customerOtpRequired")
    delivered_quantity: int = Field(alias="deliveredQuantity")
    empty_collected_quantity: int = Field(alias="emptyCollectedQuantity")

    model_config = _CAMEL


class VerifyCustomerOtpRequest(BaseModel):
    """The code the customer reads out (§7.3)."""

    otp: str = Field(max_length=10)

    model_config = _CAMEL


class VerifyCustomerOtpResponse(BaseModel):
    """The delivery is done."""

    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    delivered_quantity: int = Field(alias="deliveredQuantity")
    empty_collected_quantity: int = Field(alias="emptyCollectedQuantity")
    completed_at: UtcTime = Field(alias="completedAt")

    model_config = _CAMEL


# --- Profile ---------------------------------------------------------------------------------


class DriverProfileResponse(BaseModel):
    """The driver's own record (§8.1)."""

    id: str
    name: str
    phone: str
    employee_code: str | None = Field(default=None, alias="employeeCode")
    vehicle_number: str | None = Field(default=None, alias="vehicleNumber")
    role: str
    on_duty: bool = Field(alias="onDuty")
    avatar_initials: str | None = Field(default=None, alias="avatarInitials")

    model_config = _CAMEL


class UpdateDutyRequest(BaseModel):
    on_duty: bool = Field(alias="onDuty")

    model_config = _CAMEL


# --- Van stock -------------------------------------------------------------------------------


class DriverInventoryLine(BaseModel):
    cylinder_type: str = Field(alias="cylinderType")
    label: str
    quantity: int

    model_config = _CAMEL


class DriverInventoryResponse(BaseModel):
    """What is on this driver's van right now (§10).

    Computed from their dispatched slips, not stored. A separate van-stock table would be a
    second place the same cylinders are counted, and the two would drift the first time a
    delivery was confirmed from the office instead of the app.
    """

    full_cylinders: list[DriverInventoryLine] = Field(alias="fullCylinders")
    full_cylinder_count: int = Field(alias="fullCylinderCount")
    empty_cylinder_count: int = Field(alias="emptyCylinderCount")
    active_deliveries: int = Field(alias="activeDeliveries")

    model_config = _CAMEL
