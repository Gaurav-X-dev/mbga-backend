"""Customer V2 UPI intent and FIFO allocation contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.payments.constants import MAX_PAYMENT_AMOUNT
from app.modules.payments.schemas import UtcTime

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class CreatePaymentIntentRequest(BaseModel):
    amount: int = Field(gt=0, le=MAX_PAYMENT_AMOUNT)
    payment_channel: Literal["QR", "UPI_ID"] = Field(default="QR", alias="paymentChannel")
    model_config = _CAMEL


class PaymentIntentResponse(BaseModel):
    payment_intent_id: str = Field(alias="paymentIntentId")
    amount: int
    total_due: int = Field(alias="totalDue")
    running_balance: int = Field(alias="runningBalance")
    remaining_balance: int = Field(alias="remainingBalance")
    payment_channel: Literal["QR", "UPI_ID"] = Field(alias="paymentChannel")
    upi_id: str = Field(alias="upiId")
    payee_name: str = Field(alias="payeeName")
    upi_uri: str = Field(alias="upiUri")
    qr_image_base64: str = Field(alias="qrImageBase64")
    expires_at: UtcTime = Field(alias="expiresAt")
    model_config = _CAMEL


class SubmitPaymentIntentRequest(BaseModel):
    reference: str | None = Field(default=None, max_length=80)
    paid_at: datetime | None = Field(default=None, alias="paidAt")
    model_config = _CAMEL


class FifoAllocationResponse(BaseModel):
    invoice_id: str = Field(alias="invoiceId")
    invoice_number: str = Field(alias="invoiceNumber")
    amount_applied: int = Field(alias="amountApplied")
    pending_amount: int = Field(default=0, alias="pendingAmount")
    remaining_balance: int = Field(alias="remainingBalance")
    status: str
    model_config = _CAMEL


class CreditAfterPaymentResponse(BaseModel):
    credit_active: bool = Field(default=False, alias="creditActive")
    credit_limit: int = Field(alias="creditLimit")
    used_credit: int = Field(alias="usedCredit")
    available_credit: int = Field(alias="availableCredit")
    model_config = _CAMEL


class SubmitPaymentIntentResponse(BaseModel):
    collection_id: str = Field(alias="collectionId")
    payment_id: str = Field(alias="paymentId")
    payment_number: str | None = Field(default=None, alias="paymentNumber")
    amount_paid: int = Field(alias="amountPaid")
    running_balance: int = Field(alias="runningBalance")
    applied_amount: int = Field(alias="appliedAmount")
    pending_amount: int = Field(alias="pendingAmount")
    remaining_balance: int = Field(alias="remainingBalance")
    reconciliation_status: str = Field(alias="reconciliationStatus")
    allocations: list[FifoAllocationResponse]
    credit: CreditAfterPaymentResponse
    model_config = _CAMEL


class PaymentReceiptUploadResponse(BaseModel):
    receipt_url: str = Field(alias="receiptUrl")
    uploaded_at: UtcTime = Field(alias="uploadedAt")
    model_config = _CAMEL


class PaymentCollectionResponse(BaseModel):
    collection_id: str = Field(alias="collectionId")
    payment_id: str = Field(alias="paymentId")
    payment_number: str | None = Field(default=None, alias="paymentNumber")
    customer_id: str = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")
    amount: int
    running_balance: int = Field(alias="runningBalance")
    applied_amount: int = Field(alias="appliedAmount")
    pending_amount: int = Field(alias="pendingAmount")
    payment_channel: str = Field(alias="paymentChannel")
    upi_id: str | None = Field(default=None, alias="upiId")
    payee_name: str | None = Field(default=None, alias="payeeName")
    reference: str | None = None
    receipt_url: str | None = Field(default=None, alias="receiptUrl")
    status: str
    paid_at: UtcTime | None = Field(default=None, alias="paidAt")
    submitted_at: UtcTime | None = Field(default=None, alias="submittedAt")
    allocations: list[FifoAllocationResponse] = Field(default_factory=list)
    model_config = _CAMEL
