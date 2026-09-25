"""Request and response models for the Delivery & Dispatch screens (spec §3.12, §10).

Field names are the mobile contract's camelCase. Timestamps go out as UTC with a `Z`, because
MySQL DATETIME keeps no offset and a naive string is read by JS as local time - which on a
delivery slip would show a van dispatched five and a half hours before it was loaded.

`pendingPickup` is computed on the way out rather than stored, so it cannot drift from
`cylindersAllocated - emptiesCollected`.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.customers.business_schemas import Address
from app.modules.deliveries.constants import (
    MAX_NOTE_LENGTH,
    ConfirmationMethod,
    DeliveryStatus,
)
from app.modules.pricing.constants import CylinderType

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- The slip -------------------------------------------------------------------------------


class DeliveryItemResponse(BaseModel):
    """One cylinder type on the slip (spec §3.12 `items`)."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    quantity: int

    model_config = _CAMEL


class DeliverySlipResponse(BaseModel):
    """Spec §3.12 `DeliverySlip`."""

    id: str
    slip_number: str = Field(alias="slipNumber")
    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    customer_id: str = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")
    delivery_address: Address = Field(alias="deliveryAddress")
    delivery_site_name: str = Field(alias="deliverySiteName")
    items: list[DeliveryItemResponse]
    items_summary: str = Field(alias="itemsSummary")
    cylinders_allocated: int = Field(alias="cylindersAllocated")

    vehicle_number: str = Field(alias="vehicleNumber")
    driver_name: str = Field(alias="driverName")
    helper_name: str | None = Field(default=None, alias="helperName")

    #: A plain date - `"2026-09-26"`. A van goes out on a day; there is no delivery slot.
    scheduled_date: date = Field(alias="scheduledDate")
    dispatched_at: UtcTime | None = Field(default=None, alias="dispatchedAt")
    delivered_at: UtcTime | None = Field(default=None, alias="deliveredAt")

    empties_collected: int = Field(alias="emptiesCollected")
    #: `cylindersAllocated - emptiesCollected`. Derived, so it cannot disagree with the two.
    pending_pickup: int = Field(alias="pendingPickup")
    confirmation_method: ConfirmationMethod = Field(alias="confirmationMethod")
    status: DeliveryStatus

    failure_reason: str | None = Field(default=None, alias="failureReason")
    note: str | None = None
    #: The code minted by `POST /{id}/dispatch`, returned **only** where the deployment already
    #: exposes login OTPs (local and staging). It is how an app developer tests the confirm screen
    #: without waiting for a push. In production this is always null: the customer's "Order out
    #: for delivery" notification is the only place the code appears.
    dev_confirmation_code: str | None = Field(default=None, alias="devConfirmationCode")

    model_config = _CAMEL


# --- Requests --------------------------------------------------------------------------------


class CreateDeliverySlipRequest(BaseModel):
    """Raise a slip against a confirmed order.

    **Not one of the spec's four delivery endpoints.** §10 lists list, detail, dispatch and
    confirm, and never says where a slip comes from - the Phase 1 frontend had them seeded in a
    mock. Without this the module cannot be used at all, so it is added the way `orders.cancel`
    was, and it is what the "Schedule Delivery" action on a confirmed order calls.
    """

    order_id: str = Field(alias="orderId", max_length=36)
    vehicle_number: str = Field(alias="vehicleNumber", max_length=20)
    #: The driver's **user** id, from `GET /delivery-users`. Preferred over a typed name: it is
    #: what addresses the "new delivery assigned" notification to their phone, and it stops a
    #: slip being raised for a driver who is blocked or belongs to another merchant.
    driver_user_id: str | None = Field(default=None, alias="driverUserId", max_length=36)
    #: For a hired van whose driver has no account. One of this or `driverUserId` is required.
    driver_name: str | None = Field(default=None, alias="driverName", max_length=160)
    helper_user_id: str | None = Field(default=None, alias="helperUserId", max_length=36)
    helper_name: str | None = Field(default=None, alias="helperName", max_length=160)
    #: Defaults to the order's own scheduled delivery date, which the cut-off already decided.
    scheduled_date: date | None = Field(default=None, alias="scheduledDate")
    confirmation_method: ConfirmationMethod = Field(
        default=ConfirmationMethod.OTP, alias="confirmationMethod"
    )

    model_config = _CAMEL


class ConfirmDeliveryRequest(BaseModel):
    """Spec §10.4 `ConfirmDeliveryRequest`."""

    #: Required when `confirmationMethod = OTP`. Four digits the customer reads out.
    otp: str | None = Field(default=None, max_length=10)
    empties_collected: int = Field(alias="emptiesCollected")
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    model_config = _CAMEL


class FailDeliveryRequest(BaseModel):
    """Mark a slip failed so it can be rescheduled.

    Also an addition. `FAILED` is in the spec's `DeliveryStatus`, the list filters on it and
    §18.8 has a "Delivery failed" notification, but no endpoint sets it - and a van that comes
    back loaded has to be recordable, or the slip sits `DISPATCHED` for ever and the stock it
    took out is never returned.
    """

    reason: str = Field(max_length=MAX_NOTE_LENGTH)
    #: Whether the cylinders came back to the godown. True for a refused or missed delivery;
    #: false when they were left with the customer despite the slip not being confirmed, which
    #: the office then has to resolve by hand.
    returned_to_stock: bool = Field(default=True, alias="returnedToStock")

    model_config = _CAMEL
