"""Customer V2 UPI intents and atomic oldest-due-first settlement."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import UploadFile
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.account_state import CUSTOMER_APPROVED
from app.modules.credit.service import CreditLimitService
from app.modules.customers.models import CustomerProfile
from app.modules.driver.upi_qr import build_upi_link, png_base64
from app.modules.merchants.models import Merchant
from app.modules.payments import validation
from app.modules.payments.constants import PaymentMode, ReconciliationStatus
from app.modules.payments.models import Invoice, Payment, PaymentCollection
from app.modules.payments.numbering import NumberAllocator
from app.modules.payments.service import PaymentService
from app.modules.payments.v2_customer_schemas import (
    CreatePaymentIntentRequest,
    CreditAfterPaymentResponse,
    FifoAllocationResponse,
    PaymentIntentResponse,
    SubmitPaymentIntentRequest,
    SubmitPaymentIntentResponse,
)
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.storage.file_types import JPEG, PNG, SNIFF_BYTES, detect_content_type
from app.shared.storage.provider import StorageProvider

INTENT_TTL = timedelta(minutes=15)
CREATED = "CREATED"
SUBMITTED = "SUBMITTED"
MAX_RECEIPT_BYTES = 5 * 1024 * 1024


async def collection_allocations(session: AsyncSession, collection: PaymentCollection) -> list[FifoAllocationResponse]:
    rows = await session.execute(
        select(Payment, Invoice).join(Invoice, Payment.invoice_id == Invoice.id).where(
            Payment.collection_id == collection.id, Payment.merchant_id == collection.merchant_id,
            Invoice.merchant_id == collection.merchant_id, Invoice.customer_id == collection.customer_id,
        ).order_by(Invoice.due_at, Invoice.issued_at, Invoice.id)
    )
    return [FifoAllocationResponse(
        invoice_id=invoice.id, invoice_number=invoice.invoice_number,
        amount_applied=int(payment.applied_amount),
        pending_amount=(int(payment.amount_collected) - int(payment.applied_amount)
                        if payment.reconciliation_status == ReconciliationStatus.PENDING.value else 0),
        remaining_balance=int(invoice.balance), status=invoice.status,
    ) for payment, invoice in rows]


class CustomerV2PaymentService:
    def __init__(
        self, session: AsyncSession, actor: BusinessActor, storage: StorageProvider | None = None
    ) -> None:
        self.session = session
        self.actor = actor
        self.customer_id = actor.require_customer_id()
        self.merchant_id = actor.require_merchant_id()
        self.storage = storage

    async def create_intent(
        self, payload: CreatePaymentIntentRequest, idempotency_key: str
    ) -> PaymentIntentResponse:
        key = idempotency_key.strip()
        if not key or len(key) > 120:
            raise ApiError("INVALID_IDEMPOTENCY_KEY", 422, "Provide a valid Idempotency-Key.")

        existing = await self._intent_by_key(key)
        if existing is not None:
            if (
                int(existing.amount) != payload.amount
                or existing.payment_channel != payload.payment_channel
            ):
                raise ApiError(
                    "IDEMPOTENCY_KEY_REUSED",
                    http_status.HTTP_409_CONFLICT,
                    "This Idempotency-Key was already used with another amount.",
                )
            return self._intent_view(existing, running_balance=await self._total_due())

        customer = await self.session.get(CustomerProfile, self.customer_id)
        merchant = await self.session.get(Merchant, self.merchant_id)
        if customer is None or customer.status != CUSTOMER_APPROVED:
            raise ApiError("CUSTOMER_NOT_ACTIVE", 403, "Customer account is not active.")
        if merchant is None or not merchant.upi_id or not merchant.upi_payee_name:
            raise ApiError(
                "UPI_NOT_CONFIGURED", 409, "UPI payments are not configured for this merchant."
            )

        total_due = await self._total_due()
        if total_due <= 0:
            raise ApiError("NO_OUTSTANDING_DUE", 409, "There is no outstanding balance.")
        invoices = list(await self.session.scalars(select(Invoice).where(
            Invoice.customer_id == self.customer_id, Invoice.merchant_id == self.merchant_id,
            Invoice.balance > 0,
        )))
        reserved = await PaymentService(self.session, self.actor).pending_reservations([invoice.id for invoice in invoices])
        collectable = sum(max(int(invoice.balance) - reserved.get(invoice.id, 0), 0) for invoice in invoices)
        if payload.amount > collectable:
            raise ApiError("PAYMENT_EXCEEDS_DUE", 422, "Amount exceeds the outstanding balance.")

        now = datetime.now(UTC)
        intent_id = str(uuid4())
        upi_uri = build_upi_link(
            upi_id=merchant.upi_id,
            payee_name=merchant.upi_payee_name,
            amount=str(payload.amount),
            order_number="",  # Account-wide invoice payment supplies its own note below.
            notes=f"Invoice payment {intent_id[:8]}",
        )
        row = PaymentCollection(
            id=intent_id,
            merchant_id=self.merchant_id,
            customer_id=self.customer_id,
            amount=payload.amount,
            total_due_at_creation=total_due,
            mode=PaymentMode.UPI.value,
            payment_channel=payload.payment_channel,
            upi_id_snapshot=merchant.upi_id,
            payee_name_snapshot=merchant.upi_payee_name,
            status=CREATED,
            idempotency_key=key,
            upi_uri=upi_uri,
            expires_at=now + INTENT_TTL,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            winner = await self._intent_by_key(key)
            if winner is None:
                raise
            if int(winner.amount) != payload.amount:
                raise ApiError("IDEMPOTENCY_KEY_REUSED", 409)
            row = winner
        return self._intent_view(row, running_balance=await self._total_due())

    async def submit(
        self, intent_id: str, payload: SubmitPaymentIntentRequest
    ) -> SubmitPaymentIntentResponse:
        collection = await self.session.scalar(
            select(PaymentCollection)
            .where(
                PaymentCollection.id == intent_id,
                PaymentCollection.customer_id == self.customer_id,
                PaymentCollection.merchant_id == self.merchant_id,
            )
            .with_for_update()
        )
        if collection is None:
            raise ApiError("PAYMENT_INTENT_NOT_FOUND", 404)
        if collection.status != CREATED:
            return await self._submitted_view(collection)

        now = datetime.now(UTC)
        expires_at = collection.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            raise ApiError("PAYMENT_INTENT_EXPIRED", 409, "Generate a new payment QR.")

        reference = (payload.reference or "").strip() or None
        if not reference and not collection.receipt_storage_key:
            raise ApiError(
                "PAYMENT_EVIDENCE_REQUIRED", 422, "Provide a UPI reference or payment receipt."
            )
        used_reference = (
            await self.session.scalar(
                select(PaymentCollection.id).where(
                    PaymentCollection.merchant_id == self.merchant_id,
                    PaymentCollection.reference == reference,
                    PaymentCollection.id != collection.id,
                )
            )
            if reference
            else None
        )
        if reference and used_reference is not None:
            raise ApiError("UPI_REFERENCE_ALREADY_USED", 409, "UPI reference was already used.")

        paid_at = validation.check_paid_at(payload.paid_at, now=now)
        await self.session.scalar(
            select(CustomerProfile).where(CustomerProfile.id == self.customer_id).with_for_update()
        )
        invoices = list(
            await self.session.scalars(
                select(Invoice)
                .where(
                    Invoice.customer_id == self.customer_id,
                    Invoice.merchant_id == self.merchant_id,
                    Invoice.balance > 0,
                )
                .order_by(Invoice.due_at, Invoice.issued_at, Invoice.id)
                .with_for_update()
            )
        )
        total_due = sum(int(invoice.balance) for invoice in invoices)
        reserved = await PaymentService(self.session, self.actor).pending_reservations([invoice.id for invoice in invoices])
        collectable = sum(max(int(invoice.balance) - reserved.get(invoice.id, 0), 0) for invoice in invoices)
        if collection.amount > collectable:
            raise ApiError(
                "OUTSTANDING_DUE_CHANGED",
                409,
                "Outstanding balance changed. Generate a new payment QR.",
            )

        remaining = int(collection.amount)
        allocations: list[FifoAllocationResponse] = []
        allocator = NumberAllocator(self.session, self.merchant_id)
        collection.payment_number = await allocator.next_payment_number()
        for invoice in invoices:
            if remaining <= 0:
                break
            amount = min(remaining, max(int(invoice.balance) - reserved.get(invoice.id, 0), 0))
            if amount <= 0:
                continue
            payment = Payment(
                id=str(uuid4()),
                payment_number=await allocator.next_payment_number(),
                merchant_id=self.merchant_id,
                collection_id=collection.id,
                invoice_id=invoice.id,
                invoice_number=invoice.invoice_number,
                customer_id=self.customer_id,
                customer_name=invoice.customer_name,
                invoice_amount=invoice.total_amount,
                amount_collected=amount,
                applied_amount=0,
                mode=PaymentMode.UPI.value,
                paid_at=paid_at,
                reference=reference,
                proof_url=(
                    f"/api/v2/customer/payments/intents/{collection.id}/receipt"
                    if collection.receipt_storage_key
                    else None
                ),
                proof_captured_at=collection.receipt_uploaded_at,
                reconciliation_status=ReconciliationStatus.PENDING.value,
                collected_by_user_id=self.actor.user_id,
                collected_by_name=self.actor.display_name,
                customer_running_balance=total_due,
                note=f"Customer V2 FIFO collection {collection.id}",
                created_at=now,
                updated_at=now,
            )
            self.session.add(payment)
            allocations.append(
                FifoAllocationResponse(
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    amount_applied=0,
                    pending_amount=amount,
                    remaining_balance=int(invoice.balance),
                    status=invoice.status,
                )
            )
            remaining -= amount

        if remaining != 0:
            raise ApiError("PAYMENT_ALLOCATION_FAILED", 409)

        await self.session.flush()
        credit = await CreditLimitService(self.session).snapshot(
            self.customer_id, lock=True, include_disabled_usage=True
        )
        collection.reference = reference
        collection.paid_at = paid_at
        collection.submitted_at = now
        collection.status = SUBMITTED
        collection.remaining_balance = total_due
        collection.credit_used = credit.used
        collection.available_credit = credit.available
        collection.allocation_snapshot = json.dumps(
            [item.model_dump(by_alias=True) for item in allocations], separators=(",", ":")
        )
        collection.updated_at = now
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApiError("UPI_REFERENCE_ALREADY_USED", 409) from exc
        response = self._submitted_response(collection, allocations, credit.limit if credit.enabled else 0)
        response.credit.credit_active = credit.enabled
        return response

    async def _total_due(self) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.balance), 0)).where(
                Invoice.customer_id == self.customer_id,
                Invoice.merchant_id == self.merchant_id,
                Invoice.balance > 0,
            )
        )
        return int(total or 0)

    async def _intent_by_key(self, key: str) -> PaymentCollection | None:
        return await self.session.scalar(
            select(PaymentCollection).where(
                PaymentCollection.customer_id == self.customer_id,
                PaymentCollection.idempotency_key == key,
            )
        )

    def _intent_view(self, row: PaymentCollection, *, running_balance: int) -> PaymentIntentResponse:
        return PaymentIntentResponse(
            payment_intent_id=row.id,
            amount=int(row.amount),
            total_due=int(row.total_due_at_creation),
            running_balance=running_balance,
            remaining_balance=max(int(row.total_due_at_creation) - int(row.amount), 0),
            upi_uri=row.upi_uri,
            qr_image_base64=png_base64(row.upi_uri),
            payment_channel=row.payment_channel,
            upi_id=row.upi_id_snapshot or "",
            payee_name=row.payee_name_snapshot or "",
            expires_at=row.expires_at,
        )

    async def upload_receipt(self, intent_id: str, upload: UploadFile):
        collection = await self._owned_intent(intent_id)
        if collection.status != CREATED:
            raise ApiError("PAYMENT_INTENT_ALREADY_SUBMITTED", 409)
        expires_at = collection.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise ApiError("PAYMENT_INTENT_EXPIRED", 409, "Generate a new payment QR.")
        if self.storage is None:
            raise ApiError("SERVICE_UNAVAILABLE", 503, "Payment receipt storage is not configured.")
        head = await upload.read(SNIFF_BYTES)
        detected = detect_content_type(head, upload.filename)
        declared = (upload.content_type or "").split(";", 1)[0].strip().lower()
        if detected.content_type not in {JPEG, PNG} or declared != detected.content_type:
            raise ApiError("UNSUPPORTED_FILE_TYPE", 415, "Receipt must be a JPEG or PNG image.")
        now = datetime.now(UTC)
        extension = ".jpg" if detected.content_type == JPEG else ".png"
        key = f"customer-payments/{now:%Y/%m}/{uuid4().hex}{extension}"
        previous = collection.receipt_storage_key
        stored = await self.storage.save(key, self._receipt_chunks(head, upload))
        collection.receipt_storage_key = stored.storage_key
        collection.receipt_content_type = detected.content_type
        collection.receipt_uploaded_at = now
        collection.updated_at = now
        await self.session.commit()
        if previous and previous != stored.storage_key:
            await self.storage.delete(previous)
        return now

    async def receipt_file(self, intent_id: str):
        collection = await self._owned_intent(intent_id)
        if self.storage is None or not collection.receipt_storage_key:
            raise ApiError("PAYMENT_RECEIPT_NOT_FOUND", 404)
        try:
            return self.storage.open(collection.receipt_storage_key), (
                collection.receipt_content_type or JPEG
            )
        except FileNotFoundError as exc:
            raise ApiError("PAYMENT_RECEIPT_NOT_FOUND", 404) from exc

    async def _owned_intent(self, intent_id: str) -> PaymentCollection:
        row = await self.session.scalar(
            select(PaymentCollection).where(
                PaymentCollection.id == intent_id,
                PaymentCollection.customer_id == self.customer_id,
                PaymentCollection.merchant_id == self.merchant_id,
            )
        )
        if row is None:
            raise ApiError("PAYMENT_INTENT_NOT_FOUND", 404)
        return row

    async def _receipt_chunks(self, head: bytes, upload: UploadFile):
        total = len(head)
        if head:
            yield head
        while chunk := await upload.read(64 * 1024):
            total += len(chunk)
            if total > MAX_RECEIPT_BYTES:
                raise ApiError("FILE_TOO_LARGE", 413, "Receipt must not exceed 5 MB.")
            yield chunk

    async def _submitted_view(self, collection: PaymentCollection) -> SubmitPaymentIntentResponse:
        allocations = await collection_allocations(self.session, collection)
        customer = await self.session.get(CustomerProfile, self.customer_id)
        credit = await CreditLimitService(self.session).snapshot(
            self.customer_id, include_disabled_usage=True
        )
        response = self._submitted_response(
            collection, allocations, credit.limit if credit.enabled else 0
        )
        response.remaining_balance = await self._total_due()
        response.running_balance = response.remaining_balance
        response.credit.credit_active = credit.enabled
        response.credit.used_credit = credit.used
        response.credit.available_credit = credit.available
        return response

    @staticmethod
    def _submitted_response(
        collection: PaymentCollection,
        allocations: list[FifoAllocationResponse],
        credit_limit: int,
    ) -> SubmitPaymentIntentResponse:
        return SubmitPaymentIntentResponse(
            collection_id=collection.id,
            payment_id=collection.id,
            payment_number=collection.payment_number,
            amount_paid=int(collection.amount),
            running_balance=int(collection.remaining_balance or 0),
            applied_amount=sum(item.amount_applied for item in allocations),
            pending_amount=sum(item.pending_amount for item in allocations),
            remaining_balance=int(collection.remaining_balance or 0),
            reconciliation_status=(
                ReconciliationStatus.PENDING.value
                if collection.status == SUBMITTED
                else collection.status
            ),
            allocations=allocations,
            credit=CreditAfterPaymentResponse(
                credit_limit=credit_limit,
                used_credit=int(collection.credit_used or 0),
                available_credit=int(collection.available_credit or 0),
            ),
        )
