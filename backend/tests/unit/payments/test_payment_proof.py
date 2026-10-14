from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.authentication.constants import LoginChannel
from app.modules.payments.service import PaymentService
from app.shared.business.actor import BusinessActor


class StorageStub:
    def open(self, key: str):
        assert key == "delivery-payment-proofs/slip-1/proof.jpg"
        return iter((b"proof",))


@pytest.mark.asyncio
async def test_payment_proof_is_resolved_from_an_owned_payment():
    session = SimpleNamespace(scalar=AsyncMock())
    actor = BusinessActor(
        user_id="merchant-user",
        login_channel=LoginChannel.MERCHANT,
        display_name="Merchant",
        merchant_id="merchant-1",
    )
    service = PaymentService(session, actor, StorageStub())
    payment = SimpleNamespace(
        id="payment-1",
        merchant_id="merchant-1",
        customer_id="customer-1",
        proof_url="/api/v1/delivery/deliveries/slip-1/payment-proof",
    )
    slip = SimpleNamespace(
        payment_proof_storage_key="delivery-payment-proofs/slip-1/proof.jpg",
        payment_proof_content_type="image/jpeg",
    )
    service._owned_payment = AsyncMock(return_value=payment)
    session.scalar.return_value = slip

    stream, content_type = await service.payment_proof_file("payment-1")

    assert content_type == "image/jpeg"
    assert list(stream) == [b"proof"]
    service._owned_payment.assert_awaited_once_with("payment-1")


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (LoginChannel.MERCHANT, "/api/v1/merchant/payments/payment-1/proof"),
        (LoginChannel.CUSTOMER, "/api/v1/customer/payments/payment-1/proof"),
        (LoginChannel.ADMIN, "/api/v1/admin/payments/payment-1/proof"),
    ],
)
def test_payment_response_exposes_the_current_channel_proof_url(channel, expected):
    actor = BusinessActor(user_id="user-1", login_channel=channel, display_name="Viewer")
    service = PaymentService(SimpleNamespace(), actor)
    payment = SimpleNamespace(
        id="payment-1",
        payment_number="PAY-0001",
        invoice_id="invoice-1",
        invoice_number="MBGA/INV/0001",
        customer_id="customer-1",
        customer_name="Customer",
        invoice_amount=1000,
        amount_collected=1000,
        mode="UPI",
        paid_at="2026-10-14T10:00:00Z",
        reference="UTR-1",
        proof_url="/api/v1/delivery/deliveries/slip-1/payment-proof",
        proof_captured_at="2026-10-14T09:59:00Z",
        reconciliation_status="PENDING",
        invalid_reason=None,
        collected_by_name="Driver",
        customer_running_balance=0,
        note=None,
    )

    assert service._payment_view(payment).proof_url == expected
