"""Pydantic schemas for the Deliveries domain (API Reference §6 & §7)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.orders.schemas import OrderItemResponse


# ---------------------------------------------------------------------------
# Response schemas — §6.1 / §6.2
# ---------------------------------------------------------------------------

class DeliveryResponse(BaseModel):
    id: str
    orderNumber: str
    customerName: str
    customerPhone: str
    address: str
    timeSlotStart: str | None = None
    timeSlotEnd: str | None = None
    status: str
    distanceKm: float | None = None
    completedAt: str | None = None
    items: list[OrderItemResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §7.1 — Start Delivery
# ---------------------------------------------------------------------------

class StartDeliveryRequest(BaseModel):
    latitude: float
    longitude: float


class StartDeliveryResponse(BaseModel):
    isAtLocation: bool
    distanceMetersFromDestination: float


# ---------------------------------------------------------------------------
# §7.2 — Confirm Delivery
# ---------------------------------------------------------------------------

class ConfirmDeliveryRequest(BaseModel):
    deliveredQuantity: int = Field(ge=0)
    emptyCollectedQuantity: int = Field(ge=0)
    notes: str | None = None


class ConfirmDeliveryResponse(BaseModel):
    deliveryId: str
    customerOtpRequired: bool


# ---------------------------------------------------------------------------
# §7.3 — Verify Customer OTP
# ---------------------------------------------------------------------------

class VerifyCustomerOtpRequest(BaseModel):
    otp: str = Field(pattern=r"^[0-9]{4,6}$")


class VerifyCustomerOtpResponse(BaseModel):
    deliveryId: str
    orderNumber: str
    deliveredQuantity: int
    emptyCollectedQuantity: int
    completedAt: str
