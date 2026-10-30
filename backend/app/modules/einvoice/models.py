"""The e-invoice job queue.

**Why a queue and not a call at handover.** The invoice is raised inside the delivery
confirmation's transaction. Calling the GST portal there would put a third party's uptime in
front of a driver finishing a delivery: the portal is slow, the request times out, and the
handover that physically happened fails to record. So the confirmation queues a row and
returns, and a worker does the talking.

It is the same shape as `notification_outbox`, for the same reason, and the failure mode
it avoids is the one that slice was built to avoid.

**One job per invoice.** `invoice_id` is unique. A retried confirmation, or an operator
pressing Retry twice, must not end up asking the portal for two IRNs against one document -
the portal would reject the duplicate, but the error would be ours to explain.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class EInvoiceJob(Base):
    __tablename__ = "einvoice_jobs"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_einvoice_jobs_invoice"),
        # The worker's query: what is due, oldest first.
        Index("ix_einvoice_jobs_due", "status", "next_attempt_at"),
        # The admin screen: this merchant's failures.
        Index("ix_einvoice_jobs_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Plain columns rather than foreign keys, like the other queue tables here: a FK
    #: between two String(36) columns needs both to share a collation, and this schema has
    #: already been bitten by that on MySQL 8 against MariaDB.
    invoice_id: Mapped[str] = mapped_column(String(36), index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), index=True)

    status: Mapped[str] = mapped_column(String(20), index=True)
    #: True when this invoice's value crossed the threshold at the time it was queued. Frozen
    #: here rather than recomputed, so a later price correction cannot silently change whether
    #: a consignment was supposed to carry an e-Way Bill.
    with_eway_bill: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: When the next attempt is due. Null means "now" for a pending row.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The portal's own message, kept verbatim. NIC's errors name the field they rejected
    #: ("Buyer GSTIN is invalid"), which is the only thing that lets an accountant fix it -
    #: so it is shown to staff rather than replaced with a friendly sentence.
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: The request and response of the last attempt, for an operator reconciling with the
    #: portal. Never shown to a customer.
    last_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
