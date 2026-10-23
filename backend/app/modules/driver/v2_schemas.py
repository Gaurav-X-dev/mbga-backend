"""Delivery V2 request and response contracts for split cash/UPI collection."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.driver.schemas import (
    CollectedEmptyEntry,
    ConfirmDeliveryResponseData,
    CustomerInfoDetail,
    DeliveredItemEntry,
    DeliveryItemResponse,
    EmptyDueSummary,
    UtcTime,
)
from app.modules.payments.constants import MAX_PAYMENT_AMOUNT

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class PaymentMethodV2(StrEnum):
    CASH = "CASH"
    UPI = "UPI"
    MIXED = "MIXED"


class PaymentEntryV2(BaseModel):
    method: PaymentMethodV2
    split: str
    amount_collected: float = Field(
        alias="amountCollected", ge=0, le=MAX_PAYMENT_AMOUNT, allow_inf_nan=False
    )
    cash_amount: float | None = Field(
        default=None, alias="cashAmount", ge=0, le=MAX_PAYMENT_AMOUNT, allow_inf_nan=False
    )
    upi_amount: float | None = Field(
        default=None, alias="upiAmount", ge=0, le=MAX_PAYMENT_AMOUNT, allow_inf_nan=False
    )
    payable_amount: float = Field(alias="payableAmount", ge=0, allow_inf_nan=False)
    pending_balance: float = Field(alias="pendingBalance", ge=0, allow_inf_nan=False)
    reference: str | None = Field(default=None, max_length=80)
    proof_url: str | None = Field(default=None, alias="proofUrl", max_length=500)
    proof_captured_at: UtcTime | None = Field(default=None, alias="proofCapturedAt")
    applied_to_this_delivery: float | None = Field(
        default=None, alias="appliedToThisDelivery"
    )
    applied_to_previous_due: float | None = Field(
        default=None, alias="appliedToPreviousDue"
    )
    model_config = _CAMEL

    @model_validator(mode="after")
    def retain_single_mode_compatibility(self) -> "PaymentEntryV2":
        """Old CASH/UPI payloads remain valid; MIXED must state both portions."""
        if self.method == PaymentMethodV2.CASH:
            if self.cash_amount is None:
                self.cash_amount = self.amount_collected
            if self.upi_amount is None:
                self.upi_amount = 0
        elif self.method == PaymentMethodV2.UPI:
            if self.cash_amount is None:
                self.cash_amount = 0
            if self.upi_amount is None:
                self.upi_amount = self.amount_collected
        elif self.cash_amount is None or self.upi_amount is None:
            raise ValueError("cashAmount and upiAmount are required for MIXED payments")
        return self


class ConfirmDeliveryRequestV2(BaseModel):
    delivered_items: list[DeliveredItemEntry] = Field(alias="deliveredItems")
    collected_empties: list[CollectedEmptyEntry] = Field(alias="collectedEmpties")
    payment: PaymentEntryV2 | None = None
    driver_notes: str | None = Field(alias="driverNotes", default=None)
    model_config = _CAMEL


class VerifyCustomerOtpResponseDataV2(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    status: str
    completed_at: str = Field(alias="completedAt")
    total_delivered_quantity: int = Field(alias="totalDeliveredQuantity")
    delivered_items: list[DeliveryItemResponse] = Field(alias="deliveredItems")
    total_empty_collected_quantity: int = Field(alias="totalEmptyCollectedQuantity")
    empty_collected_items: list[DeliveryItemResponse] = Field(alias="emptyCollectedItems")
    empty_due_summary: EmptyDueSummary = Field(alias="emptyDueSummary")
    payment: PaymentEntryV2 | dict[str, Any] = Field(default_factory=dict)
    model_config = _CAMEL


class CompletedDeliveryDetailResponseDataV2(BaseModel):
    delivery_id: str = Field(alias="deliveryId")
    order_number: str = Field(alias="orderNumber")
    status: str
    delivery_date: str = Field(alias="deliveryDate")
    completed_at: str = Field(alias="completedAt")
    customer: CustomerInfoDetail
    delivered_items: list[DeliveryItemResponse] = Field(alias="deliveredItems")
    empty_items: list[DeliveryItemResponse] = Field(alias="emptyItems")
    payment: PaymentEntryV2 | dict[str, Any] = Field(default_factory=dict)
    driver_notes: str | None = Field(alias="driverNotes", default=None)
    model_config = _CAMEL


__all__ = [
    "CompletedDeliveryDetailResponseDataV2",
    "ConfirmDeliveryRequestV2",
    "ConfirmDeliveryResponseData",
    "PaymentEntryV2",
    "PaymentMethodV2",
    "VerifyCustomerOtpResponseDataV2",
]
