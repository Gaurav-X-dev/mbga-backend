"""Merchant review and atomic reconciliation of Customer V2 FIFO collections."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import CustomerProfile
from app.modules.payments import validation
from app.modules.payments.constants import ReconciliationStatus
from app.modules.payments.models import Invoice, Payment, PaymentCollection
from app.modules.payments.schemas import ReconcilePaymentRequest
from app.modules.payments.service import PaymentService
from app.modules.payments.v2_customer_schemas import (
    FifoAllocationResponse,
    PaymentCollectionResponse,
)
from app.modules.payments.v2_customer_service import collection_allocations
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.storage.file_types import JPEG
from app.shared.storage.provider import StorageProvider

CREATED = "CREATED"
SUBMITTED = "SUBMITTED"


class MerchantV2PaymentService:
    def __init__(
        self, session: AsyncSession, actor: BusinessActor, storage: StorageProvider | None = None
    ) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()
        self.storage = storage

    async def list_collections(self, status: str | None) -> list[PaymentCollectionResponse]:
        statement = select(PaymentCollection).where(
            PaymentCollection.merchant_id == self.merchant_id,
            PaymentCollection.status != CREATED,
        )
        if status:
            wanted = status.strip().upper()
            if wanted == ReconciliationStatus.PENDING.value:
                wanted = SUBMITTED
            if wanted not in {SUBMITTED, "RECONCILED", "INVALID"}:
                raise validation.invalid(
                    "status", "unknown_status", "Use PENDING, RECONCILED or INVALID."
                )
            statement = statement.where(PaymentCollection.status == wanted)
        rows = await self.session.scalars(statement.order_by(PaymentCollection.submitted_at.desc()))
        return [await self._view(row) for row in rows]

    async def get_collection(self, collection_id: str) -> PaymentCollectionResponse:
        return await self._view(await self._owned(collection_id))

    async def reconcile(
        self, collection_id: str, payload: ReconcilePaymentRequest
    ) -> PaymentCollectionResponse:
        collection = await self._owned(collection_id, lock=True)
        if collection.status != SUBMITTED:
            raise ApiError(
                "PAYMENT_ALREADY_RECONCILED",
                409,
                f"This collection is already {collection.status.lower()}.",
            )
        reason = validation.check_reason(payload.reconciled, payload.reason)
        invoice_ids = list(await self.session.scalars(select(Payment.invoice_id).where(
            Payment.collection_id == collection.id, Payment.merchant_id == self.merchant_id,
        )))
        invoices = {row.id: row for row in await self.session.scalars(
            select(Invoice).where(Invoice.id.in_(invoice_ids), Invoice.merchant_id == self.merchant_id)
            .order_by(Invoice.id).with_for_update().execution_options(populate_existing=True)
        )}
        if len(invoices) != len(set(invoice_ids)):
            raise ApiError("PAYMENT_COLLECTION_INVOICE_MISSING", 409)
        payments = list(
            await self.session.scalars(
                select(Payment)
                .where(
                    Payment.collection_id == collection.id,
                    Payment.merchant_id == self.merchant_id,
                )
                .order_by(Payment.invoice_id)
                .with_for_update().execution_options(populate_existing=True)
            )
        )
        if not payments:
            raise ApiError("PAYMENT_COLLECTION_EMPTY", 409)

        now = datetime.now(UTC)
        if payload.reconciled:
            for payment in payments:
                invoice = invoices[payment.invoice_id]
                delta = int(payment.amount_collected) - int(payment.applied_amount)
                if delta > invoice.balance:
                    raise ApiError("PAYMENT_EXCEEDS_BALANCE", 409, "Invoice balance changed; review this payment.")
                if delta:
                    PaymentService._apply_to_invoice(invoice, delta=delta, now=now)
                payment.applied_amount = payment.amount_collected
            collection.allocation_snapshot = json.dumps([
                FifoAllocationResponse(
                    invoice_id=payment.invoice_id,
                    invoice_number=payment.invoice_number,
                    amount_applied=int(payment.applied_amount),
                    remaining_balance=int(invoices[payment.invoice_id].balance),
                    status=invoices[payment.invoice_id].status,
                ).model_dump(by_alias=True) for payment in payments
            ], separators=(",", ":"))

        next_status = (
            ReconciliationStatus.RECONCILED.value
            if payload.reconciled
            else ReconciliationStatus.INVALID.value
        )
        for payment in payments:
            payment.reconciliation_status = next_status
            payment.invalid_reason = None if payload.reconciled else reason
            payment.reconciled_at = now
            payment.reconciled_by_name = self.actor.display_name
            payment.updated_at = now
        collection.status = next_status
        collection.updated_at = now
        await self.session.commit()
        return await self.get_collection(collection.id)

    async def receipt_file(self, collection_id: str):
        collection = await self._owned(collection_id)
        if self.storage is None or not collection.receipt_storage_key:
            raise ApiError("PAYMENT_RECEIPT_NOT_FOUND", 404)
        try:
            return self.storage.open(collection.receipt_storage_key), (
                collection.receipt_content_type or JPEG
            )
        except FileNotFoundError as exc:
            raise ApiError("PAYMENT_RECEIPT_NOT_FOUND", 404) from exc

    async def _owned(self, collection_id: str, *, lock: bool = False) -> PaymentCollection:
        statement = select(PaymentCollection).where(
            PaymentCollection.id == collection_id,
            PaymentCollection.merchant_id == self.merchant_id,
            PaymentCollection.status != CREATED,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self.session.scalar(statement)
        if row is None:
            raise ApiError("PAYMENT_COLLECTION_NOT_FOUND", 404)
        return row

    async def _view(self, row: PaymentCollection) -> PaymentCollectionResponse:
        customer = await self.session.get(CustomerProfile, row.customer_id)
        allocations = await collection_allocations(self.session, row)
        return PaymentCollectionResponse(
            collection_id=row.id,
            payment_id=row.id,
            payment_number=row.payment_number,
            customer_id=row.customer_id,
            customer_name=customer.name if customer else "Unknown customer",
            amount=int(row.amount),
            running_balance=await PaymentService(self.session, self.actor)._running_balance(row.customer_id),
            applied_amount=sum(item.amount_applied for item in allocations),
            pending_amount=sum(item.pending_amount for item in allocations),
            payment_channel=row.payment_channel,
            upi_id=row.upi_id_snapshot,
            payee_name=row.payee_name_snapshot,
            reference=row.reference,
            receipt_url=(
                f"/api/v2/merchant/payment-collections/{row.id}/receipt"
                if row.receipt_storage_key
                else None
            ),
            status=(ReconciliationStatus.PENDING.value if row.status == SUBMITTED else row.status),
            paid_at=row.paid_at,
            submitted_at=row.submitted_at,
            allocations=allocations,
        )
