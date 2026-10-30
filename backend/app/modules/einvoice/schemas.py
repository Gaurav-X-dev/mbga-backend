"""What the panel is told about one invoice's filing."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EInvoiceStatusResponse(BaseModel):
    """The filing state of one invoice, for the compliance block on the invoice screen.

    `lastError` is the portal's own sentence, not a friendly rewrite of it. NIC names the
    field it rejected - "Buyer GSTIN is invalid", "Pincode does not belong to the state" -
    and that sentence is the only thing that lets an accountant fix the record. Hiding it
    behind "Something went wrong" turns a five-minute correction into a support ticket.
    """

    #: None when this invoice was never queued. That happens for two different reasons, and
    #: `eligible` is what tells them apart: a B2C sale that will never be filed, or an invoice
    #: raised before this slice existed, which still can be.
    status: str | None = None
    #: True when the buyer has a GSTIN, so an IRN applies to this invoice at all.
    eligible: bool = False
    #: Whether an e-Way Bill was asked for, decided from the invoice value when it was queued.
    with_eway_bill: bool = Field(default=False, alias="withEwayBill")
    attempts: int = 0
    last_error: str | None = Field(default=None, alias="lastError")
    next_attempt_at: datetime | None = Field(default=None, alias="nextAttemptAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    #: Copied from the invoice so one call fills the whole block.
    irn: str | None = None
    acknowledgement_number: str | None = Field(default=None, alias="acknowledgementNumber")
    eway_bill_number: str | None = Field(default=None, alias="ewayBillNumber")
    #: False when the invoice is not eligible, or is already filed - the panel uses this to
    #: decide whether to offer Retry rather than reimplementing the rule.
    can_retry: bool = Field(default=False, alias="canRetry")

    model_config = ConfigDict(populate_by_name=True)
