"""Queuing an invoice for the portal, and working the queue.

Two halves that deliberately never run together:

* `queue_for` is called inside the delivery confirmation's transaction. It decides whether
  this invoice needs a government reference at all, and writes one row. It talks to nobody.
* `EInvoiceDispatcher.run_once` is the worker. It picks up what is due, builds the payload,
  calls the provider and writes the result back onto the invoice.

The split is what keeps a driver's handover independent of the GST portal's uptime.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.einvoice.client import PerioneClient
from app.modules.einvoice.constants import (
    MAX_ATTEMPTS,
    RETRY_BACKOFF_MINUTES,
    EInvoiceStatus,
    needs_eway_bill,
)
from app.modules.einvoice.models import EInvoiceJob
from app.modules.einvoice.payload import PayloadError, build_generate_payload
from app.modules.einvoice.schemas import EInvoiceStatusResponse
from app.modules.payments.invoice_documents import read_snapshot
from app.modules.payments.models import Invoice

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatchReport:
    """What one worker pass did, for the operator reading the log."""

    considered: int = 0
    generated: int = 0
    rejected: int = 0
    retrying: int = 0
    abandoned: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def queue_for(
    session: AsyncSession,
    invoice: Invoice,
    *,
    now: datetime | None = None,
) -> EInvoiceJob | None:
    """Queue this invoice for an IRN, if it needs one.

    Runs in the caller's transaction, so the job commits with the delivery it belongs to.
    Returns None when no government reference applies - which is the ordinary case for a
    domestic LPG customer, and not a failure.

    The decision is made once, here, from the invoice as issued:

    * **IRN** when the buyer has a GSTIN. A sale to an unregistered customer is B2C and the
      portal rejects it, so sending it would only manufacture errors for staff to read.
    * **e-Way Bill** when the invoice is worth more than fifty thousand rupees. Frozen onto
      the job rather than read again later, so a correction cannot quietly change what was
      asked for.
    """
    if not (invoice.gstin or "").strip():
        return None

    moment = now or datetime.now(UTC)
    job = EInvoiceJob(
        id=str(uuid4()),
        invoice_id=invoice.id,
        merchant_id=invoice.merchant_id,
        status=EInvoiceStatus.PENDING.value,
        with_eway_bill=needs_eway_bill(invoice.total_amount),
        attempts=0,
        next_attempt_at=None,
        created_at=moment,
        updated_at=moment,
    )
    session.add(job)

    # Two confirmations arriving together both reach here. The unique key on invoice_id stops
    # the second, and the first one's row is the right answer - the invoice does need exactly
    # one IRN, and asking the portal twice is what produces a duplicate rejection.
    savepoint = await session.begin_nested()
    try:
        await session.flush()
    except IntegrityError:
        await savepoint.rollback()
        return await session.scalar(select(EInvoiceJob).where(EInvoiceJob.invoice_id == invoice.id))
    await savepoint.commit()
    return job


async def einvoice_view(session: AsyncSession, invoice: Invoice) -> EInvoiceStatusResponse:
    """The filing state of one invoice, for the panel's compliance block."""
    job = await session.scalar(select(EInvoiceJob).where(EInvoiceJob.invoice_id == invoice.id))
    filed = bool((invoice.irn or "").strip())
    # The same rule `queue_for` applies, asked again now: the buyer may have been given a
    # GSTIN after this invoice was raised, and an invoice issued before this slice existed
    # has no job at all. Both are filable; a genuine B2C sale is not.
    eligible = bool((invoice.gstin or "").strip())
    return EInvoiceStatusResponse(
        status=job.status if job else None,
        eligible=eligible,
        with_eway_bill=bool(job.with_eway_bill) if job else False,
        attempts=job.attempts if job else 0,
        last_error=job.last_error if job else None,
        next_attempt_at=job.next_attempt_at if job else None,
        completed_at=job.completed_at if job else None,
        irn=invoice.irn,
        acknowledgement_number=invoice.acknowledgement_number,
        eway_bill_number=invoice.eway_bill_number,
        # Offered for a job that stopped, and for an eligible invoice that was never queued -
        # the second is how a back-dated invoice, or one raised before this existed, gets
        # filed at all. Never for one already filed: asking the portal again for a document
        # that has an IRN is the duplicate it rejects.
        can_retry=bool(
            eligible
            and not filed
            and (
                job is None
                or job.status in (EInvoiceStatus.FAILED.value, EInvoiceStatus.ABANDONED.value)
            )
        ),
    )


async def requeue(session: AsyncSession, invoice: Invoice) -> EInvoiceJob | None:
    """Put a stopped job back in the queue after its data was corrected.

    Creates the job when there is none and the invoice has since become eligible - a customer
    whose GSTIN was added after the sale was billed is exactly that case, and without this
    the only way to file it would be by hand.

    The attempt count is reset, because the thing being retried is a different document from
    the one that failed. Nothing is sent here; the worker picks it up on its next pass.
    """
    if (invoice.irn or "").strip():
        # Already filed. Re-queuing would ask the portal for a second IRN against one
        # document, which it refuses - and the refusal would look like our bug.
        return None

    moment = datetime.now(UTC)
    job = await session.scalar(select(EInvoiceJob).where(EInvoiceJob.invoice_id == invoice.id))
    if job is None:
        # `queue_for` runs inside the delivery confirmation's transaction and leaves the
        # commit to it. Here there is no outer transaction to ride on, so the row has to be
        # committed or the panel reports "queued" over a row that is rolled back.
        created = await queue_for(session, invoice, now=moment)
        await session.commit()
        return created

    job.status = EInvoiceStatus.PENDING.value
    job.attempts = 0
    job.next_attempt_at = None
    job.last_error = None
    job.with_eway_bill = needs_eway_bill(invoice.total_amount)
    job.updated_at = moment
    await session.commit()
    return job


class EInvoiceDispatcher:
    """Works the queue: one pass over whatever is due."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        client: PerioneClient | None = None,
        dry_run: bool = False,
    ) -> None:
        self.session = session
        self.settings = settings
        self.dry_run = dry_run
        self._client = client

    async def run_once(self) -> DispatchReport:
        report = DispatchReport()
        moment = datetime.now(UTC)
        for job in await self._due(moment):
            report.considered += 1
            await self._process(job, report, moment)
        return report

    async def _due(self, moment: datetime) -> list[EInvoiceJob]:
        """Pending and failed jobs whose back-off has elapsed, oldest first."""
        rows = await self.session.scalars(
            select(EInvoiceJob)
            .where(
                EInvoiceJob.status.in_(
                    (EInvoiceStatus.PENDING.value, EInvoiceStatus.FAILED.value)
                ),
                or_(
                    EInvoiceJob.next_attempt_at.is_(None),
                    EInvoiceJob.next_attempt_at <= moment.replace(tzinfo=None),
                ),
            )
            .order_by(EInvoiceJob.created_at)
            .limit(self.settings.einvoice_batch_size)
        )
        return list(rows)

    async def _process(self, job: EInvoiceJob, report: DispatchReport, moment: datetime) -> None:
        invoice = await self.session.get(Invoice, job.invoice_id)
        if invoice is None:  # pragma: no cover - the FK makes this unreachable
            await self._settle(job, EInvoiceStatus.ABANDONED, "The invoice no longer exists.", moment)
            report.abandoned += 1
            return

        # An IRN already on the row means somebody filed this by hand, or an earlier attempt
        # succeeded and the result was written before the job was. Either way the portal has
        # the document and asking again would be the duplicate it rejects.
        if (invoice.irn or "").strip():
            await self._settle(job, EInvoiceStatus.DONE, None, moment)
            report.skipped += 1
            return

        snapshot = read_snapshot(invoice)
        if snapshot is None:
            await self._settle(
                job,
                EInvoiceStatus.ABANDONED,
                "This invoice was issued before the printable snapshot existed, so it cannot be filed automatically.",
                moment,
            )
            report.abandoned += 1
            return

        try:
            payload = build_generate_payload(
                snapshot,
                invoice_number=invoice.invoice_number,
                with_eway_bill=bool(job.with_eway_bill),
            )
        except PayloadError as error:
            # The document is incomplete. Retrying cannot fix missing data, so it stops here
            # with the reason on the row for somebody to correct.
            await self._settle(job, EInvoiceStatus.FAILED, str(error), moment, final=True)
            report.rejected += 1
            return

        if self.dry_run:
            logger.info(
                "Would file %s (e-Way Bill: %s)", invoice.invoice_number, "yes" if job.with_eway_bill else "no"
            )
            report.skipped += 1
            return

        client = self._client or self._build_client()
        if client is None:
            # Nothing configured. The row stays exactly as it is, so turning the feature on
            # later files it rather than skipping it.
            report.skipped += 1
            return

        result = await client.generate(payload, version=self.settings.einvoice_schema_version)
        job.last_response = json.dumps(result.raw, separators=(",", ":"))[:65000] if result.raw else None

        if result.ok and result.irn:
            invoice.irn = result.irn
            invoice.acknowledgement_number = result.acknowledgement_number
            invoice.acknowledgement_date = _portal_time(result.acknowledgement_date)
            invoice.eway_bill_number = result.eway_bill_number
            invoice.eway_bill_date = _portal_time(result.eway_bill_date)
            invoice.updated_at = moment
            await self._settle(job, EInvoiceStatus.DONE, None, moment)
            report.generated += 1
            return

        job.attempts += 1
        if result.retryable and job.attempts < MAX_ATTEMPTS:
            delay = RETRY_BACKOFF_MINUTES[min(job.attempts - 1, len(RETRY_BACKOFF_MINUTES) - 1)]
            job.status = EInvoiceStatus.FAILED.value
            job.last_error = (result.error or "")[:500] or None
            job.next_attempt_at = (moment + timedelta(minutes=delay)).replace(tzinfo=None)
            job.updated_at = moment
            await self.session.commit()
            report.retrying += 1
            return

        # Either the portal rejected the document itself, or it has been tried enough. Both
        # need a person, and the difference matters to that person: a rejection is theirs to
        # fix, an exhausted retry is the provider's to explain.
        final_status = EInvoiceStatus.FAILED if not result.retryable else EInvoiceStatus.ABANDONED
        await self._settle(job, final_status, (result.error or "Unknown error")[:500], moment, final=True)
        if final_status is EInvoiceStatus.FAILED:
            report.rejected += 1
        else:
            report.abandoned += 1

    async def _settle(
        self,
        job: EInvoiceJob,
        status: EInvoiceStatus,
        error: str | None,
        moment: datetime,
        *,
        final: bool = False,
    ) -> None:
        job.status = status.value
        job.last_error = error
        job.updated_at = moment
        if final:
            # No next attempt: a null here on a failed row means "given up", and the operator
            # can still press Retry, which clears it.
            job.next_attempt_at = None
        if status in (EInvoiceStatus.DONE, EInvoiceStatus.SKIPPED):
            job.completed_at = moment
        await self.session.commit()

    def _build_client(self) -> PerioneClient | None:
        settings = self.settings
        required = (
            settings.einvoice_email,
            settings.einvoice_username,
            settings.einvoice_password,
            settings.einvoice_client_id,
            settings.einvoice_client_secret,
            settings.einvoice_bearer_token,
            settings.einvoice_gstin,
            settings.einvoice_ip_address,
        )
        if not settings.einvoice_enabled or not all(required):
            return None
        self._client = PerioneClient(
            base_url=settings.einvoice_base_url,
            email=str(settings.einvoice_email),
            username=str(settings.einvoice_username),
            password=str(settings.einvoice_password),
            client_id=str(settings.einvoice_client_id),
            client_secret=str(settings.einvoice_client_secret),
            bearer_token=str(settings.einvoice_bearer_token),
            gstin=str(settings.einvoice_gstin),
            ip_address=str(settings.einvoice_ip_address),
        )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _portal_time(value: str | None) -> datetime | None:
    """`2026-10-23 17:02:00` as the portal writes it, which is IST."""
    if not value:
        return None
    from zoneinfo import ZoneInfo

    for pattern in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(str(value), pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC).replace(tzinfo=None)
    logger.warning("Unreadable timestamp from the e-invoice provider: %r", value)
    return None
