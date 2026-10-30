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
from app.modules.einvoice.eway_client import PerioneEwayClient
from app.modules.einvoice.eway_payload import build_eway_payload
from app.modules.einvoice.constants import (
    MAX_ATTEMPTS,
    RETRY_BACKOFF_MINUTES,
    EInvoiceStatus,
    needs_eway_bill,
    needs_irn,
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
    """Queue this invoice for whatever the government requires of it, if anything.

    Runs in the caller's transaction, so the job commits with the delivery it belongs to.
    Returns None when nothing applies - the ordinary domestic cylinder sale, and not a
    failure.

    The two rules are asked separately, because they are separate rules:

    * **IRN** when the buyer has a GSTIN. A sale to an unregistered customer is B2C and the
      portal rejects it, so sending it would only manufacture errors for staff to read.
    * **e-Way Bill** when the invoice is worth more than fifty thousand rupees. This asks
      nothing about the buyer: the bill follows the goods, so an unregistered customer's
      consignment needs one on exactly the same terms.

    Either one on its own is enough to queue. The case that makes this matter is the second
    without the first - an unregistered customer billed over the threshold - which an earlier
    version of this function dropped on the floor, because it tested the GSTIN before it
    tested anything else. Goods then moved without the document the law requires them to
    carry, and nothing anywhere said so.

    Both answers are frozen onto the row rather than re-read later, so neither a price
    correction nor a GSTIN added next week can change what this handover was supposed to file.
    """
    with_irn = needs_irn(invoice.gstin)
    with_eway_bill = needs_eway_bill(invoice.total_amount)
    if not with_irn and not with_eway_bill:
        return None

    moment = now or datetime.now(UTC)
    job = EInvoiceJob(
        id=str(uuid4()),
        invoice_id=invoice.id,
        merchant_id=invoice.merchant_id,
        status=EInvoiceStatus.PENDING.value,
        with_eway_bill=with_eway_bill,
        with_irn=with_irn,
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
    # The same two rules `queue_for` applies, asked again now: the buyer may have been given
    # a GSTIN after this invoice was raised, and an invoice issued before this slice existed
    # has no job at all. Both are filable.
    with_irn = needs_irn(invoice.gstin)
    with_eway_bill = job.with_eway_bill if job else needs_eway_bill(invoice.total_amount)
    eligible = with_irn or bool(with_eway_bill)
    # What "filed" means depends on which route this invoice takes. An IRN settles the
    # registered case; an unregistered consignment is settled by its e-Way Bill, and asking
    # for an IRN it can never have would leave Retry offered forever.
    filed = (
        bool((invoice.irn or "").strip())
        if with_irn
        else bool((job.eway_bill_number if job else None) or "")
    )
    return EInvoiceStatusResponse(
        status=job.status if job else None,
        eligible=eligible,
        with_irn=with_irn,
        with_eway_bill=bool(with_eway_bill),
        attempts=job.attempts if job else 0,
        last_error=job.last_error if job else None,
        next_attempt_at=job.next_attempt_at if job else None,
        completed_at=job.completed_at if job else None,
        irn=invoice.irn,
        acknowledgement_number=invoice.acknowledgement_number,
        eway_bill_number=invoice.eway_bill_number or (job.eway_bill_number if job else None),
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

    if job.eway_bill_number and not needs_irn(invoice.gstin):
        # An unregistered consignment that already has its bill. There is nothing else this
        # route can ask the portal for, and asking again would be the duplicate it refuses.
        return None

    job.status = EInvoiceStatus.PENDING.value
    job.attempts = 0
    job.next_attempt_at = None
    job.last_error = None
    # Both answers are taken again, because what is being retried is the corrected document:
    # a GSTIN added since the sale moves this job onto the IRN route, which is exactly the
    # correction an operator presses Retry for.
    job.with_eway_bill = needs_eway_bill(invoice.total_amount)
    job.with_irn = needs_irn(invoice.gstin)
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
        eway_client: PerioneEwayClient | None = None,
        dry_run: bool = False,
    ) -> None:
        self.session = session
        self.settings = settings
        self.dry_run = dry_run
        self._client = client
        self._eway_client = eway_client

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
        # the document and asking again would be the duplicate it rejects. The same is true
        # of a bill already raised on the e-Way Bill route, which has no IRN to show for it.
        if job.with_irn and (invoice.irn or "").strip():
            await self._settle(job, EInvoiceStatus.DONE, None, moment)
            report.skipped += 1
            return
        if not job.with_irn and (job.eway_bill_number or "").strip():
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

        # Which of the two provider APIs this invoice goes to was decided when it was
        # queued, and both payloads are built from the same frozen snapshot.
        try:
            if job.with_irn:
                payload = build_generate_payload(
                    snapshot,
                    invoice_number=invoice.invoice_number,
                    with_eway_bill=bool(job.with_eway_bill),
                )
            else:
                payload = build_eway_payload(snapshot, invoice_number=invoice.invoice_number)
        except PayloadError as error:
            # The document is incomplete. Retrying cannot fix missing data, so it stops here
            # with the reason on the row for somebody to correct.
            await self._settle(job, EInvoiceStatus.FAILED, str(error), moment, final=True)
            report.rejected += 1
            return

        if self.dry_run:
            logger.info(
                "Would file %s (%s)",
                invoice.invoice_number,
                "IRN with e-Way Bill"
                if job.with_irn and job.with_eway_bill
                else "IRN" if job.with_irn else "e-Way Bill only, buyer unregistered",
            )
            report.skipped += 1
            return

        if not job.with_irn:
            await self._file_eway_only(job, invoice, payload, report, moment)
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

    async def _file_eway_only(
        self,
        job: EInvoiceJob,
        invoice: Invoice,
        payload: dict,
        report: DispatchReport,
        moment: datetime,
    ) -> None:
        """Raise an e-Way Bill for a consignment that has no IRN to carry one.

        Kept beside the IRN path rather than folded into it: the two speak to different APIs
        with different credentials and different success shapes, and a single branching block
        would hide which outcome belongs to which.
        """
        client = self._eway_client or self._build_eway_client()
        if client is None:
            # Nothing configured for the e-Way Bill API. The row stays pending, so filling
            # the credentials in later files it rather than having skipped it silently.
            report.skipped += 1
            return

        result = await client.generate(payload)
        job.last_response = json.dumps(result.raw, separators=(",", ":"))[:65000] if result.raw else None

        if result.ok and result.eway_bill_number:
            job.eway_bill_number = result.eway_bill_number
            # The invoice row carries it too, so the panel and the printed document read the
            # same number whichever route produced it.
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

    def _build_eway_client(self) -> PerioneEwayClient | None:
        """The e-Way Bill API's own connection.

        Separate credentials from the e-invoice API - the provider issues a `PEWAYS` client
        pair for it - but they fall back to the e-invoice ones, because a provider that has
        put both APIs behind one set of keys is the likelier arrangement than two deployments
        of this platform.
        """
        settings = self.settings
        client_id = settings.eway_client_id or settings.einvoice_client_id
        client_secret = settings.eway_client_secret or settings.einvoice_client_secret
        bearer = settings.eway_bearer_token or settings.einvoice_bearer_token
        required = (
            settings.einvoice_email,
            settings.einvoice_username,
            settings.einvoice_password,
            client_id,
            client_secret,
            bearer,
            settings.einvoice_gstin,
            settings.einvoice_ip_address,
        )
        if not settings.einvoice_enabled or not all(required):
            return None
        self._eway_client = PerioneEwayClient(
            base_url=settings.eway_base_url or settings.einvoice_base_url,
            email=str(settings.einvoice_email),
            username=str(settings.einvoice_username),
            password=str(settings.einvoice_password),
            client_id=str(client_id),
            client_secret=str(client_secret),
            bearer_token=str(bearer),
            gstin=str(settings.einvoice_gstin),
            ip_address=str(settings.einvoice_ip_address),
            version=settings.eway_api_version,
        )
        return self._eway_client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._eway_client is not None:
            await self._eway_client.aclose()
            self._eway_client = None


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
