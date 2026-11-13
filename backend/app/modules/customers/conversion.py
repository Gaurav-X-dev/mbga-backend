"""Target-type edits use the same registration rules and evidence ownership checks."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.authentication.account_state import CUSTOMER_SUSPENDED, CUSTOMER_UNDER_REVIEW
from app.modules.business_catalogue.service import BusinessCatalogueService
from app.modules.customer_access.models import CustomerBrand, CustomerOutlet
from app.modules.customers.business_schemas import (
    Address,
    CustomerRegistrationRequest,
    SiteSubmission,
)
from app.modules.customers.constants import KycStatus
from app.modules.customers.mapping import address_of
from app.modules.customers.models import CustomerDeliverySite, KycApplication
from app.shared.exceptions.api_error import ApiError


async def validate_and_apply_conversion(session, actor, profile, payload, registration):
    if profile.status == CUSTOMER_SUSPENDED:
        raise ApiError(
            "INVALID_STATUS_TRANSITION",
            409,
            "Reactivate this customer before changing its registration details.",
        )
    target = payload.customer_type.value if payload.customer_type else profile.customer_type
    changes = payload.model_fields_set
    address = (
        payload.delivery_address if payload.delivery_address is not None else address_of(profile)
    )
    sites = payload.sites
    if sites is None:
        sites = []
        definition = await BusinessCatalogueService(session).require_active_customer_type(target)
        if definition.requires_delivery_sites:
            existing = await session.scalars(
                select(CustomerDeliverySite).where(
                    CustomerDeliverySite.customer_id == profile.id,
                    CustomerDeliverySite.is_active.is_(True),
                )
            )
            sites = [
                SiteSubmission(
                    name=site.name,
                    address=Address(
                        line1=site.address_line1,
                        line2=site.address_line2,
                        city=site.address_city,
                        state=site.address_state,
                        pincode=site.address_pincode,
                        latitude=site.latitude,
                        longitude=site.longitude,
                        deliveryInstructions=site.delivery_instructions,
                    ),
                    contactName=site.contact_name,
                    contactMobile=site.contact_mobile,
                    isPrimary=site.is_primary,
                )
                for site in existing
            ]
    request = CustomerRegistrationRequest(
        customerType=target,
        businessName=payload.business_name if "business_name" in changes else profile.name or "",
        ownerName=(payload.owner_name or "")
        if "owner_name" in changes
        else profile.owner_name or "",
        email=payload.email if "email" in changes else profile.email,
        deliveryAddress=address,
        documents=payload.documents or [],
        sites=sites,
    )
    data = await registration.validate(
        request, actor, require_documents=True, existing_profile=profile
    )
    link = await session.get(CustomerOutlet, profile.id)
    shared = ()
    brand = (
        await session.get(CustomerBrand, link.brand_id)
        if link
        else await session.scalar(
            select(CustomerBrand).where(CustomerBrand.owner_customer_id == profile.id)
        )
    )
    if brand:
        siblings = tuple(
            await session.scalars(
                select(CustomerOutlet.customer_id).where(CustomerOutlet.brand_id == brand.id)
            )
        )
        shared = (
            (brand.owner_customer_id,) if brand and brand.owner_customer_id else ()
        ) + siblings
    await registration.ensure_numbers_are_unique(profile, data, shared_customer_ids=shared)
    now = datetime.now(UTC)
    await registration.apply_profile_fields(profile, data, now)
    await registration.link_documents(profile, data, now)
    await registration.replace_sites(profile, data, now)
    # A new classification/evidence set must not inherit the old KYC approval.
    profile.status = CUSTOMER_UNDER_REVIEW
    profile.kyc_status = KycStatus.PENDING.value
    profile.rejection_reason = None
    profile.submitted_at = now
    profile.reviewed_at = None
    profile.reviewed_by = None
    pending_id = await session.scalar(
        select(KycApplication.id).where(
            KycApplication.customer_id == profile.id, KycApplication.status == "PENDING"
        )
    )
    application = await registration.open_application(profile, actor.user_id, now)
    if pending_id is None:
        registration.queue_submission_events(profile, application)
