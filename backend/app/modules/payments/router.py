"""Invoice and payment routes (spec §12), built per channel.

Both apps read the same rows and see different slices of them, so this is a
`build_payment_router(channel)` factory rather than two hand-written routers that would drift.
The difference between the channels is **scope**, applied in the service's `WHERE`: merchant
staff see their merchant's invoices and payments, a customer sees their own.

Writes are merchant-only, and that is not a scoping decision. Recording a collection is an act
of the merchant's books - the person doing it is holding the notes or looking at a statement -
so a customer marking their own invoice paid is not a permission the platform can offer.

Permissions follow spec §2.1: `payments.view` reads, `payments.collect` records, and
`payments.reconcile` settles against the bank. All three are already seeded.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, CustomerActorDep
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant
from app.modules.orders.models import Order
from app.modules.payments.invoice_documents import (
    build_issue_snapshot,
    document_payload,
    merchant_settings_view,
    read_snapshot,
)
from app.modules.payments.invoice_rendering import render_html, render_pdf
from app.modules.payments.schemas import (
    CustomerPaymentSummary,
    InvoiceComplianceUpdate,
    InvoiceResponse,
    MerchantInvoiceSettingsUpdate,
    PaymentResponse,
    ReconcilePaymentRequest,
    RecordPaymentRequest,
)
from app.modules.payments.service import (
    InvoiceFilters,
    PaymentFilters,
    PaymentService,
)
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

InvoiceIdPath = Annotated[str, Path(alias="invoiceId", max_length=36)]
PaymentIdPath = Annotated[str, Path(alias="paymentId", max_length=36)]
CustomerIdPath = Annotated[str, Path(alias="customerId", max_length=36)]


def build_payment_router(channel: LoginChannel) -> APIRouter:
    """Build the invoice and payment routes for one channel."""
    is_customer = channel is LoginChannel.CUSTOMER
    is_admin = channel is LoginChannel.ADMIN
    router = APIRouter(tags=[f"{channel.value.title()} Payments"])

    channel_only = Depends(require_login_channel(channel))
    actor_dependency = (
        CustomerActorDep if is_customer else AdminMerchantActorDep if is_admin else ActorDep
    )
    staff_guards = [channel_only]
    if is_admin:
        staff_guards.append(Depends(require_permission("merchants.view")))

    # A customer reading their own payments needs no permission - the scope already limits them
    # to their own rows, and a customer holds no role in the merchant's matrix.
    read_guards = (
        [channel_only]
        if is_customer
        else [
            *staff_guards,
            Depends(require_permission("payments.view")),
        ]
    )

    def build_service(
        actor: actor_dependency,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> PaymentService:
        """FastAPI caches `get_db_session` per request, so the actor and the service share one
        session and therefore one transaction."""
        return PaymentService(session, actor)

    ServiceDep = Annotated[PaymentService, Depends(build_service)]

    # --- Invoices ---------------------------------------------------------------------------

    @router.get(
        "/invoices",
        response_model=list[InvoiceResponse],
        dependencies=read_guards,
        responses=error_responses(401, 403),
        summary="List invoices",
    )
    async def list_invoices(
        service: ServiceDep,
        customer_id: Annotated[
            str | None, Query(alias="customerId", max_length=36, description="Staff only.")
        ] = None,
        open_only: Annotated[
            bool, Query(alias="openOnly", description="Only invoices with a balance owing.")
        ] = False,
    ) -> list[InvoiceResponse]:
        """Invoices, newest issued first (spec §12.2).

        `openOnly=true` is what the Record Payment picker lists - an invoice already settled in
        full cannot take another payment, so offering it is offering an error.
        """
        return await service.list_invoices(
            InvoiceFilters(customer_id=customer_id, open_only=open_only)
        )

    @router.get(
        "/invoices/{invoiceId}",
        response_model=InvoiceResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Invoice detail",
    )
    async def get_invoice(invoice_id: InvoiceIdPath, service: ServiceDep) -> InvoiceResponse:
        """One invoice. Somebody else's is a 404, never a 403."""
        return await service.get_invoice(invoice_id)

    async def _document(invoice_id: str, service: PaymentService) -> dict:
        invoice = await service.get_invoice_row(invoice_id)
        snapshot = read_snapshot(invoice)
        if snapshot is None:
            # Legacy invoices created before the document module cannot be made historically
            # perfect because their old profile data was not stored.  They remain readable, and
            # all invoices issued after this release carry the immutable snapshot above.
            order = await service.session.get(Order, invoice.order_id)
            customer = await service.session.get(CustomerProfile, invoice.customer_id)
            if order is None:
                snapshot = {"version": 0, "documentType": "TAX_INVOICE" if invoice.is_gst_invoice else "CASH_MEMO", "merchant": {}, "customer": {"name": invoice.customer_name}, "order": {"orderNumber": invoice.order_number}, "dispatch": {}, "items": [], "tax": {"taxableAmount": invoice.amount, "gstAmount": invoice.gst_amount, "gstPercent": invoice.gst_percent, "totalAmount": invoice.total_amount}, "settings": {}}
            else:
                snapshot = await build_issue_snapshot(
                    service.session, invoice=invoice, order=order, customer=customer, delivered=None
                )
        return document_payload(invoice, snapshot)

    @router.get(
        "/invoices/{invoiceId}/document",
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Universal invoice document data",
    )
    async def get_invoice_document(invoice_id: InvoiceIdPath, service: ServiceDep) -> dict:
        """Same frozen invoice payload for Merchant, Customer and Admin applications."""
        return await _document(invoice_id, service)

    @router.get(
        "/invoices/{invoiceId}/document.html",
        response_class=HTMLResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Printable universal invoice",
    )
    async def get_invoice_document_html(invoice_id: InvoiceIdPath, service: ServiceDep) -> HTMLResponse:
        document = await _document(invoice_id, service)
        return HTMLResponse(
            render_html(document),
            headers={"Content-Disposition": f'inline; filename="{document["invoiceNumber"]}.html"'},
        )

    @router.get(
        "/invoices/{invoiceId}/document.pdf",
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Download universal invoice PDF",
    )
    async def download_invoice_document_pdf(invoice_id: InvoiceIdPath, service: ServiceDep) -> Response:
        """A real downloadable PDF; use the HTML endpoint for browser print-preview layout."""
        document = await _document(invoice_id, service)
        filename = f'{document["invoiceNumber"].replace("/", "-")}.pdf'
        return Response(
            render_pdf(document),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get(
        "/invoices/{invoiceId}/document/download",
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        include_in_schema=False,
    )
    async def download_invoice_document_alias(invoice_id: InvoiceIdPath, service: ServiceDep) -> Response:
        """Backward-friendly download alias for browser and Admin-panel integrations."""
        return await download_invoice_document_pdf(invoice_id, service)

    # Invoice brand/bank/terms are stored on the merchant and copied into every newly issued
    # invoice. Admin supplies merchantId (the normal AdminMerchantActorDep scope); customers
    # cannot read or edit a merchant's banking configuration.
    if not is_customer:

        @router.get(
            "/invoice-settings",
            dependencies=read_guards,
            responses=error_responses(401, 403),
            summary="Get merchant invoice template settings",
        )
        async def get_invoice_settings(
            actor: actor_dependency,
            session: Annotated[AsyncSession, Depends(get_db_session)],
        ) -> dict:
            merchant = await session.get(Merchant, actor.require_merchant_id())
            return merchant_settings_view(merchant) if merchant else {}

        @router.patch(
            "/invoice-settings",
            dependencies=[*staff_guards, Depends(require_permission("payments.reconcile"))],
            responses=error_responses(401, 403, 404, 422),
            summary="Update merchant invoice template settings",
        )
        async def update_invoice_settings(
            payload: MerchantInvoiceSettingsUpdate,
            actor: actor_dependency,
            session: Annotated[AsyncSession, Depends(get_db_session)],
        ) -> dict:
            merchant = await session.get(Merchant, actor.require_merchant_id())
            if merchant is None:  # actor scope normally prevents this; keep the endpoint safe.
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(merchant, field, value)
            await session.commit()
            return merchant_settings_view(merchant)

    # --- Payments ---------------------------------------------------------------------------

    @router.get(
        "/payments",
        response_model=list[PaymentResponse],
        dependencies=read_guards,
        responses=error_responses(401, 403),
        summary="List payments",
    )
    async def list_payments(
        service: ServiceDep,
        customer_id: Annotated[
            str | None, Query(alias="customerId", max_length=36, description="Staff only.")
        ] = None,
        reconciliation_status: Annotated[
            str | None,
            Query(
                alias="reconciliationStatus",
                description="`PENDING` | `RECONCILED` | `INVALID` | `ALL`.",
                max_length=20,
            ),
        ] = None,
        search: Annotated[
            str | None,
            Query(
                description="Payment number, invoice number, customer name or reference.",
                max_length=120,
            ),
        ] = None,
    ) -> list[PaymentResponse]:
        """Payments, newest collected first (spec §12.3).

        Ordered by when the money changed hands, not by when it was typed in. The two differ
        whenever a driver collects cash at the gate and the office records it that evening.
        """
        return await service.list_payments(
            PaymentFilters(
                customer_id=customer_id,
                reconciliation_status=reconciliation_status,
                search=search,
            )
        )

    @router.get(
        "/payments/{paymentId}",
        response_model=PaymentResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Payment detail",
    )
    async def get_payment(payment_id: PaymentIdPath, service: ServiceDep) -> PaymentResponse:
        """One receipt (spec §12.4)."""
        return await service.get_payment(payment_id)

    @router.get(
        "/customers/{customerId}/payments/summary",
        response_model=CustomerPaymentSummary,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Customer payment summary",
    )
    async def payment_summary(
        customer_id: CustomerIdPath, service: ServiceDep
    ) -> CustomerPaymentSummary:
        """What this customer has been billed, has paid, and still owes (spec §12.1).

        Summed from the invoices on every read rather than kept as a running total, so it cannot
        drift from the rows it describes. A customer asking for somebody else's gets a 404.
        """
        return await service.summary(customer_id)

    # --- Writes: merchant only ----------------------------------------------------------------

    if not is_customer:

        @router.patch(
            "/invoices/{invoiceId}/compliance",
            dependencies=[*staff_guards, Depends(require_permission("payments.reconcile"))],
            responses=error_responses(401, 403, 404, 422),
            summary="Record manual e-Invoice/e-Way/transport references",
        )
        async def update_invoice_compliance(
            invoice_id: InvoiceIdPath,
            payload: InvoiceComplianceUpdate,
            service: ServiceDep,
        ) -> dict:
            invoice = await service.get_invoice_row(invoice_id)
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(invoice, field, value)
            await service.session.commit()
            return await _document(invoice_id, service)

        @router.post(
            "/payments",
            response_model=PaymentResponse,
            status_code=status.HTTP_201_CREATED,
            dependencies=[*staff_guards, Depends(require_permission("payments.collect"))],
            responses=error_responses(401, 403, 404, 409, 422),
            summary="Record a payment",
        )
        async def record_payment(
            payload: RecordPaymentRequest, service: ServiceDep
        ) -> PaymentResponse:
            """Collect money against an open invoice (spec §12.5).

            Cash is reconciled immediately - the person recording it is holding the notes. UPI
            and NEFT land `PENDING` until somebody matches the reference against a statement,
            and the reference is required for exactly that reason.

            A `422` names the field: `amount` for a figure above the balance, `reference` for a
            missing UTR. `409` means the invoice is already settled in full.
            """
            return await service.record(payload)

        @router.post(
            "/payments/{paymentId}/reconcile",
            response_model=PaymentResponse,
            dependencies=[*staff_guards, Depends(require_permission("payments.reconcile"))],
            responses=error_responses(401, 403, 404, 409, 422),
            summary="Reconcile a payment",
        )
        async def reconcile_payment(
            payment_id: PaymentIdPath, payload: ReconcilePaymentRequest, service: ServiceDep
        ) -> PaymentResponse:
            """Settle a pending payment against the bank statement.

            **An addition.** §12 has no endpoint for it, but `ReconciliationStatus` has three
            values and the list filters on all three, so `PENDING` would be a state nothing
            could ever leave.

            `reconciled: false` puts the money back on the invoice and requires a reason: a
            customer who believes they have paid is about to be told they still owe, and the
            person who decides that deserves to leave a note behind.
            """
            return await service.reconcile(payment_id, payload)

    return router
