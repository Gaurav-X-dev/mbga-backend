"""Request and response models for invoices and payments (spec §3.14, §3.15, §12).

Field names are the mobile contract's camelCase. Timestamps go out as UTC with a `Z`, because
MySQL DATETIME keeps no offset and a naive string is read by JS as local time - which on a
payment would show money collected five and a half hours before it was.

`balance` and `status` are returned but never accepted: they are derived from the payments
applied to an invoice, and letting a client set them would make the two disagree.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.payments.constants import (
    MAX_NOTE_LENGTH,
    MAX_PAYMENT_AMOUNT,
    MAX_REFERENCE_LENGTH,
    InvoiceStatus,
    PaymentMode,
    ReconciliationStatus,
)

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- Invoices --------------------------------------------------------------------------------


class InvoiceResponse(BaseModel):
    """Spec §3.14 `Invoice`."""

    id: str
    invoice_number: str = Field(alias="invoiceNumber")
    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    customer_id: str = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")

    #: Taxable value. `gstAmount` is broken **out of** `totalAmount`, never added on top.
    amount: int
    gst_percent: int = Field(alias="gstPercent")
    gst_amount: int = Field(alias="gstAmount")
    total_amount: int = Field(alias="totalAmount")

    paid_amount: int = Field(alias="paidAmount")
    balance: int
    status: InvoiceStatus

    issued_at: UtcTime = Field(alias="issuedAt")
    due_at: UtcTime = Field(alias="dueAt")
    #: True once `dueAt` has passed and something is still owed. Computed on the way out so it
    #: cannot go stale in the table the way a stored flag would.
    is_overdue: bool = Field(alias="isOverdue")

    is_gst_invoice: bool = Field(alias="isGstInvoice")
    gstin: str | None = None

    model_config = _CAMEL


# --- Payments --------------------------------------------------------------------------------


class PaymentResponse(BaseModel):
    """Spec §3.15 `Payment`."""

    id: str
    payment_number: str = Field(alias="paymentNumber")
    invoice_id: str = Field(alias="invoiceId")
    invoice_number: str = Field(alias="invoiceNumber")
    customer_id: str = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")

    invoice_amount: int = Field(alias="invoiceAmount")
    amount_collected: int = Field(alias="amountCollected")
    mode: PaymentMode
    paid_at: UtcTime = Field(alias="paidAt")
    reference: str | None = None

    reconciliation_status: ReconciliationStatus = Field(alias="reconciliationStatus")
    invalid_reason: str | None = Field(default=None, alias="invalidReason")
    collected_by: str | None = Field(default=None, alias="collectedBy")
    #: What the customer still owed immediately after this payment. Frozen at that moment, so a
    #: receipt printed today keeps showing today's balance after next week's invoice is raised.
    customer_running_balance: int = Field(alias="customerRunningBalance")
    note: str | None = None

    model_config = _CAMEL


class CustomerPaymentSummary(BaseModel):
    """Spec §3.20 `CustomerPaymentSummary`. The header of the customer's Payments tab."""

    total_invoiced: int = Field(alias="totalInvoiced")
    total_paid: int = Field(alias="totalPaid")
    #: Sum of open invoice balances. What the customer owes right now.
    running_balance: int = Field(alias="runningBalance")
    #: The part of that which is already past its due date.
    overdue_amount: int = Field(alias="overdueAmount")
    #: INVALID payments are excluded - money that never arrived is not a last payment.
    last_payment_at: UtcTime | None = Field(default=None, alias="lastPaymentAt")

    model_config = _CAMEL


# --- Requests --------------------------------------------------------------------------------


class RecordPaymentRequest(BaseModel):
    """Spec §12.5 `RecordPaymentRequest`."""

    invoice_id: str = Field(alias="invoiceId", max_length=36)
    #: Whole rupees, greater than zero and no more than the invoice's balance. Over-collection
    #: is refused rather than held as credit: the platform has no customer wallet, so a credit
    #: balance would be money with nowhere to live.
    amount: int = Field(gt=0, le=MAX_PAYMENT_AMOUNT)
    mode: PaymentMode
    #: UTR, UPI transaction id, cheque number. Required for anything but cash.
    reference: str | None = Field(default=None, max_length=MAX_REFERENCE_LENGTH)
    #: When the money actually changed hands, which is not when it was typed in. Defaults to now.
    paid_at: UtcTime | None = Field(default=None, alias="paidAt")
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    model_config = _CAMEL


class ReconcilePaymentRequest(BaseModel):
    """Settle a pending payment against the bank statement.

    **An addition.** §12 has no endpoint for it, but `ReconciliationStatus` has three values and
    the list filters on all three, so `PENDING` would otherwise be a state nothing could ever
    leave - and the accountant's whole job on this screen is leaving it.
    """

    #: True when the money was found in the statement, false when it was not.
    reconciled: bool
    #: Required when `reconciled` is false. Read by whoever chases the customer.
    reason: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    model_config = _CAMEL
