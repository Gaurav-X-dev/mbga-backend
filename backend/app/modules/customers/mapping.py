"""Database rows to mobile-contract responses.

Every customer, application and document response in the project is built here. Keeping it
in one module is what stops the merchant list, the merchant detail and the KYC screens from
each growing their own slightly different idea of what a `Customer` looks like — and it is
the single place that has to be correct about never emitting an unmasked identifier.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.business_schemas import (
    Address,
    CustomerResponse,
    DeliverySiteResponse,
    KycApplicationResponse,
    KycDocumentResponse,
)
from app.modules.customers.constants import to_mobile_account_status, to_mobile_document_status
from app.modules.customers.models import (
    CustomerDeliverySite,
    CustomerDocument,
    CustomerProfile,
    KycApplication,
)

# Balance and order history come from modules that do not exist yet. They are reported as the
# contract's documented empty values rather than invented, and this constant marks every
# place that has to change when the invoice module lands.
UNIMPLEMENTED_RUNNING_BALANCE = 0


def address_of(profile: CustomerProfile) -> Address:
    return Address(
        line1=profile.address_line1 or "",
        line2=profile.address_line2,
        city=profile.address_city or "",
        state=profile.address_state or "",
        pincode=profile.address_pincode or "",
    )


def site_response(site: CustomerDeliverySite) -> DeliverySiteResponse:
    return DeliverySiteResponse(
        id=site.id,
        name=site.name,
        address=Address(
            line1=site.address_line1,
            line2=site.address_line2,
            city=site.address_city,
            state=site.address_state,
            pincode=site.address_pincode,
        ),
        contact_name=site.contact_name,
        contact_mobile=_national(site.contact_mobile),
        is_primary=site.is_primary,
    )


def document_response(document: CustomerDocument) -> KycDocumentResponse:
    """Spec §3.4. The masked value is read from its own column and never derived here.

    If masking happened at render time it would need the plaintext, which would mean
    decrypting on every list request — so the mask is computed once, at write time, and this
    function cannot accidentally emit a full number because it never holds one.
    """
    return KycDocumentResponse(
        type=document.document_type,
        number_masked=document.number_masked or "",
        # The display name, not the storage key. `fileId` is the handle for §17.2.
        file_name=document.original_filename,
        file_id=document.file_id,
        uploaded_at=document.submitted_at,
        status=to_mobile_document_status(document.status),
    )


def customer_response(
    profile: CustomerProfile,
    *,
    sites: list[CustomerDeliverySite],
    documents: list[CustomerDocument],
    application: KycApplication | None = None,
) -> CustomerResponse:
    return CustomerResponse(
        id=profile.id,
        code=profile.code,
        customer_type=profile.customer_type,
        business_name=profile.name,
        owner_name=profile.owner_name,
        mobile=_national(profile.mobile_number) or "",
        email=profile.email,
        account_status=to_mobile_account_status(profile.status),
        kyc_status=profile.kyc_status,
        pricing_tier=profile.pricing_tier,
        delivery_address=address_of(profile),
        sites=[site_response(site) for site in _primary_first(sites)],
        documents=[document_response(document) for document in documents],
        gstin=profile.gst_number,
        registered_at=profile.registered_at or profile.created_at,
        approved_at=profile.approved_at,
        rejection_reason=profile.rejection_reason,
        running_balance=UNIMPLEMENTED_RUNNING_BALANCE,
        last_order_at=None,
        application_id=application.id if application else None,
    )


def application_response(
    application: KycApplication,
    profile: CustomerProfile,
    *,
    sites: list[CustomerDeliverySite],
    documents: list[CustomerDocument],
) -> KycApplicationResponse:
    return KycApplicationResponse(
        id=application.id,
        customer_id=profile.id,
        customer_type=profile.customer_type,
        business_name=profile.name,
        owner_name=profile.owner_name,
        mobile=_national(profile.mobile_number) or "",
        email=profile.email,
        documents=[document_response(document) for document in documents],
        delivery_address=address_of(profile),
        sites=[site_response(site) for site in _primary_first(sites)],
        status=application.status,
        submitted_at=application.submitted_at,
        reviewed_at=application.reviewed_at,
        reviewed_by=application.reviewed_by_name,
        rejection_reason=application.rejection_reason,
    )


def _primary_first(sites: list[CustomerDeliverySite]) -> list[CustomerDeliverySite]:
    """Spec §3.6: industrial customers list the primary site first."""
    return sorted(sites, key=lambda site: (not site.is_primary, site.name))


def _national(mobile: str | None) -> str | None:
    """The apps display and send 10-digit numbers; storage keeps the +91 form."""
    if not mobile:
        return None
    return mobile.removeprefix("+91")


class CustomerViewLoader:
    """Loads the related rows a customer response needs, for one customer or for a page.

    The batch method exists because a list of 50 customers rendered one at a time would run
    101 queries. It runs three.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sites_for(self, customer_ids: list[str]) -> dict[str, list[CustomerDeliverySite]]:
        if not customer_ids:
            return {}
        rows = await self.session.scalars(
            select(CustomerDeliverySite).where(
                CustomerDeliverySite.customer_id.in_(customer_ids),
                CustomerDeliverySite.is_active.is_(True),
            )
        )
        grouped: dict[str, list[CustomerDeliverySite]] = {}
        for site in rows:
            grouped.setdefault(site.customer_id, []).append(site)
        return grouped

    async def documents_for(self, customer_ids: list[str]) -> dict[str, list[CustomerDocument]]:
        if not customer_ids:
            return {}
        rows = await self.session.scalars(
            select(CustomerDocument)
            .where(CustomerDocument.customer_id.in_(customer_ids))
            .order_by(CustomerDocument.submitted_at)
        )
        grouped: dict[str, list[CustomerDocument]] = {}
        for document in rows:
            grouped.setdefault(document.customer_id, []).append(document)
        return grouped

    async def latest_applications_for(self, customer_ids: list[str]) -> dict[str, KycApplication]:
        """The most recent application per customer — the one the apps show."""
        if not customer_ids:
            return {}
        rows = await self.session.scalars(
            select(KycApplication)
            .where(KycApplication.customer_id.in_(customer_ids))
            .order_by(KycApplication.submitted_at, KycApplication.created_at)
        )
        # Ordered ascending and overwritten, so the last write per customer is the newest.
        return {application.customer_id: application for application in rows}

    async def customer_view(self, profile: CustomerProfile) -> CustomerResponse:
        sites = await self.sites_for([profile.id])
        documents = await self.documents_for([profile.id])
        applications = await self.latest_applications_for([profile.id])
        return customer_response(
            profile,
            sites=sites.get(profile.id, []),
            documents=documents.get(profile.id, []),
            application=applications.get(profile.id),
        )

    async def customer_views(self, profiles: list[CustomerProfile]) -> list[CustomerResponse]:
        ids = [profile.id for profile in profiles]
        sites = await self.sites_for(ids)
        documents = await self.documents_for(ids)
        applications = await self.latest_applications_for(ids)
        return [
            customer_response(
                profile,
                sites=sites.get(profile.id, []),
                documents=documents.get(profile.id, []),
                application=applications.get(profile.id),
            )
            for profile in profiles
        ]

    async def application_views(
        self, applications: list[KycApplication], profiles: dict[str, CustomerProfile]
    ) -> list[KycApplicationResponse]:
        ids = [application.customer_id for application in applications]
        sites = await self.sites_for(ids)
        documents = await self.documents_for(ids)
        return [
            application_response(
                application,
                profiles[application.customer_id],
                sites=sites.get(application.customer_id, []),
                documents=documents.get(application.customer_id, []),
            )
            for application in applications
            if application.customer_id in profiles
        ]
