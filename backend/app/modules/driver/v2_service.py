"""Delivery V2 service for CASH, UPI and split CASH+UPI collections."""

from datetime import UTC, datetime

from fastapi import status as http_status
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip
from app.modules.driver.schemas import PaymentSummaryResponseData
from app.modules.driver.service import PAYMENT_PROOF_ERROR, DriverService
from app.modules.driver.v2_models import DeliveryPaymentBreakdownV2
from app.modules.driver.v2_schemas import (
    CompletedDeliveryDetailResponseDataV2,
    PaymentEntryV2,
    PaymentMethodV2,
    VerifyCustomerOtpResponseDataV2,
)
from app.modules.payments.constants import PaymentMode, ReconciliationStatus
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.schemas import RecordPaymentRequest
from app.modules.payments.service import PaymentService
from app.shared.exceptions.api_error import ApiError


class DriverV2Service(DriverService):
    def _payment_proof_url(self, slip_id: str) -> str:
        return f"/api/v2/delivery/deliveries/{slip_id}/payment-proof"

    async def _record_payment_intent(
        self, slip: DeliverySlip, payment: PaymentEntryV2 | None
    ) -> None:
        if payment is None:
            return

        amount = round(payment.amount_collected)
        cash = round(payment.cash_amount or 0)
        upi = round(payment.upi_amount or 0)
        self._validate_breakdown(payment.method, amount, cash, upi)
        if amount <= 0:
            slip.payment_mode = None
            slip.payment_amount = None
            slip.payment_reference = None
            current = await self.session.get(DeliveryPaymentBreakdownV2, slip.id)
            if current is not None:
                await self.session.delete(current)
            return

        if upi:
            self._require_upi_evidence(slip, payment, upi)

        payable = await self._collectable(slip)
        if amount > payable:
            raise ApiError(
                "PAYMENT_EXCEEDS_PAYABLE",
                http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"This customer owes {payable} in all, so {amount} cannot be collected.",
            )

        now = datetime.now(UTC)
        row = await self.session.get(DeliveryPaymentBreakdownV2, slip.id)
        if row is None:
            row = DeliveryPaymentBreakdownV2(
                delivery_id=slip.id,
                merchant_id=slip.merchant_id,
                driver_user_id=self.driver_user_id,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
        row.method = payment.method.value
        row.split = "full" if amount == payable else "partial"
        row.amount_collected = amount
        row.cash_amount = cash
        row.upi_amount = upi
        row.payable_amount = payable
        row.pending_balance = payable - amount
        row.proof_url = slip.payment_proof_url if upi else None
        row.proof_captured_at = slip.payment_proof_captured_at if upi else None
        row.qr_amount = int(slip.qr_amount or 0) if upi else None
        row.qr_generated_at = slip.qr_generated_at if upi else None
        row.updated_at = now

        slip.payment_mode = payment.method.value
        slip.payment_amount = amount
        slip.payment_reference = (payment.reference or "").strip() or None

    @staticmethod
    def _validate_breakdown(
        method: PaymentMethodV2, amount: int, cash: int, upi: int
    ) -> None:
        valid = cash + upi == amount
        if method == PaymentMethodV2.CASH:
            valid = valid and cash == amount and upi == 0
        elif method == PaymentMethodV2.UPI:
            valid = valid and cash == 0 and upi == amount
        else:
            valid = valid and cash > 0 and upi > 0
        if not valid:
            raise ApiError(
                "PAYMENT_BREAKDOWN_INVALID",
                http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                "cashAmount and upiAmount must match the selected method and amountCollected.",
            )

    @staticmethod
    def _require_upi_evidence(
        slip: DeliverySlip, payment: PaymentEntryV2, upi_amount: int
    ) -> None:
        qr_matches = (
            slip.qr_generated_at is not None
            and int(slip.qr_amount or 0) == upi_amount
        )
        proof_matches = (
            payment.proof_url is not None
            and payment.proof_url == slip.payment_proof_url
            and payment.proof_captured_at is not None
            and slip.payment_proof_captured_at is not None
            and _same_instant(
                payment.proof_captured_at, slip.payment_proof_captured_at
            )
            and bool(slip.payment_proof_storage_key)
        )
        if not (qr_matches and proof_matches):
            raise ApiError("UPI_EVIDENCE_REQUIRED", 400, PAYMENT_PROOF_ERROR)

    async def _bank_payment(self, slip: DeliverySlip) -> None:
        breakdown = await self.session.get(DeliveryPaymentBreakdownV2, slip.id)
        if breakdown is None:
            await super()._bank_payment(slip)
            return
        if breakdown.amount_collected <= 0:
            return

        invoice = await self.session.scalar(
            select(Invoice).where(Invoice.order_id == slip.order_id)
        )
        if invoice is None:
            return

        note = f"Collected on delivery {slip.order_number}"
        existing_rows = list(
            await self.session.scalars(
                select(Payment).where(
                    Payment.merchant_id == slip.merchant_id,
                    Payment.customer_id == slip.customer_id,
                    Payment.collected_by_user_id == self.driver_user_id,
                    Payment.note == note,
                    Payment.reconciliation_status
                    != ReconciliationStatus.INVALID.value,
                )
            )
        )
        existing_cash = sum(
            row.amount_collected
            for row in existing_rows
            if row.mode == PaymentMode.CASH.value
        )
        existing_upi = sum(
            row.amount_collected
            for row in existing_rows
            if row.mode == PaymentMode.UPI.value
        )
        remaining_by_mode = [
            (PaymentMode.CASH, max(0, breakdown.cash_amount - existing_cash)),
            (PaymentMode.UPI, max(0, breakdown.upi_amount - existing_upi)),
        ]
        if not any(amount for _mode, amount in remaining_by_mode):
            return

        other_invoices = list(
            await self.session.scalars(
                select(Invoice)
                .where(
                    Invoice.customer_id == slip.customer_id,
                    Invoice.merchant_id == slip.merchant_id,
                    Invoice.id != invoice.id,
                    Invoice.balance > 0,
                )
                .order_by(Invoice.issued_at, Invoice.id)
            )
        )
        targets = [invoice, *other_invoices]
        payments = PaymentService(self.session, self._merchant_actor(slip))
        for mode, remaining in remaining_by_mode:
            for target in targets:
                if remaining <= 0:
                    break
                share = min(remaining, int(target.balance))
                if share <= 0:
                    continue
                await payments.record(
                    RecordPaymentRequest(
                        invoiceId=target.id,
                        amount=share,
                        mode=mode,
                        reference=(
                            slip.payment_reference if mode == PaymentMode.UPI else None
                        ),
                        note=note,
                    ),
                    reference_required=False,
                    proof_url=(
                        breakdown.proof_url if mode == PaymentMode.UPI else None
                    ),
                    proof_captured_at=(
                        breakdown.proof_captured_at
                        if mode == PaymentMode.UPI
                        else None
                    ),
                )
                remaining -= share

    async def verify_customer_otp_v2(
        self, slip_id: str, otp: str
    ) -> VerifyCustomerOtpResponseDataV2:
        base = await super().verify_customer_otp(slip_id, otp)
        payment = await self._breakdown_payment(slip_id)
        return VerifyCustomerOtpResponseDataV2(
            **base.model_dump(exclude={"payment"}), payment=payment
        )

    async def get_completed_detail_v2(
        self, slip_id: str
    ) -> CompletedDeliveryDetailResponseDataV2:
        base = await super().get_completed_detail(slip_id)
        payment = await self._breakdown_payment(slip_id, fallback=base.payment)
        return CompletedDeliveryDetailResponseDataV2(
            delivery_id=base.id,
            **base.model_dump(exclude={"id", "payment"}),
            payment=payment,
        )

    async def payment_summary_v2(self, slip_id: str) -> PaymentSummaryResponseData:
        summary = await super().payment_summary(slip_id)
        return summary.model_copy(update={"modes": ["CASH", "UPI", "MIXED"]})

    async def _breakdown_payment(
        self, slip_id: str, fallback: dict[str, object] | None = None
    ) -> PaymentEntryV2 | dict[str, object]:
        row = await self.session.get(DeliveryPaymentBreakdownV2, slip_id)
        if row is None:
            return fallback or {}
        return PaymentEntryV2(
            method=PaymentMethodV2(row.method),
            split=row.split,
            amountCollected=float(row.amount_collected),
            cashAmount=float(row.cash_amount),
            upiAmount=float(row.upi_amount),
            payableAmount=float(row.payable_amount),
            pendingBalance=float(row.pending_balance),
            proofUrl=row.proof_url,
            proofCapturedAt=row.proof_captured_at,
        )


def _same_instant(left: datetime, right: datetime) -> bool:
    def utc(value: datetime) -> datetime:
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)

    return utc(left) == utc(right)
