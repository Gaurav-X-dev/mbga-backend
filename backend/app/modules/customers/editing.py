"""Scoped contact/address edits; authentication, KYC and historical orders remain unchanged."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.business_catalogue.service import BusinessCatalogueService
from app.modules.customers.business_schemas import Address, DocumentSubmission, SiteSubmission
from app.modules.customers.constants import CustomerType
from app.modules.customers.mapping import CustomerViewLoader
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.customers.validators import FieldErrors, validate_address
from app.shared.exceptions.api_error import ApiError
from app.shared.validation.names import check_name


class CustomerEditRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)
    customer_type: CustomerType | None = Field(default=None, alias="customerType")
    priority_code: str | None = Field(default=None, alias="priorityCode", max_length=30)
    business_name: str | None = Field(
        default=None, alias="businessName", min_length=1, max_length=160
    )
    owner_name: str | None = Field(default=None, alias="ownerName", max_length=160)
    email: EmailStr | None = None
    delivery_address: Address | None = Field(default=None, alias="deliveryAddress")
    documents: list[DocumentSubmission] | None = Field(default=None, max_length=30)
    sites: list[SiteSubmission] | None = Field(default=None, max_length=25)
    reason: str = Field(min_length=3, max_length=255)

    @field_validator("business_name", "owner_name")
    @classmethod
    def validate_names(cls, value, info):
        return (
            check_name(value, field=info.field_name, required=False) if value is not None else None
        )

    @model_validator(mode="after")
    def require_changes(self):
        changes = self.model_fields_set - {"reason"}
        if (
            ("customer_type" in changes and self.customer_type is None)
            or not changes
            or ("business_name" in changes and not self.business_name)
            or ("delivery_address" in changes and self.delivery_address is None)
        ):
            raise ValueError(
                "Supply a non-empty customer edit; name and address cannot be cleared."
            )
        return self


async def edit_customer(session, actor, customer_id, payload, *, commit=True, registration=None):
    profile = await session.scalar(
        select(CustomerProfile)
        .where(
            CustomerProfile.id == customer_id,
            CustomerProfile.merchant_id == actor.require_merchant_id(),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if profile is None:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    changes = payload.model_fields_set - {"reason"}
    type_changed = "customer_type" in changes and payload.customer_type != profile.customer_type
    revalidate = type_changed or "documents" in changes or "sites" in changes
    if revalidate:
        if registration is None:
            raise ApiError(
                "VALIDATION_ERROR",
                422,
                "Type changes require the complete customer registration validation flow.",
            )
        from app.modules.customers.conversion import validate_and_apply_conversion

        await validate_and_apply_conversion(session, actor, profile, payload, registration)
    if "priority_code" in changes:
        from app.modules.logistics.policy import priority_code

        profile.priority_code = (
            await priority_code(session, profile.merchant_id, payload.priority_code)
            if payload.priority_code
            else None
        )
    if payload.delivery_address is not None:
        errors = FieldErrors()
        address = validate_address(payload.delivery_address, errors)
        errors.raise_if_any()
        for name, value in address.items():
            setattr(profile, name if name == "delivery_instructions" else "address_" + name, value)
    for incoming, column in (
        ("business_name", "name"),
        ("owner_name", "owner_name"),
        ("email", "email"),
    ):
        if incoming in changes:
            setattr(profile, column, getattr(payload, incoming) or None)
    now = datetime.now(UTC)
    type_changed = "customer_type" in changes and payload.customer_type != profile.customer_type
    if not revalidate and (
        type_changed or (payload.delivery_address is not None and profile.customer_type)
    ):
        target_type = (
            payload.customer_type.value
            if payload.customer_type is not None
            else profile.customer_type
        )
        definition = await BusinessCatalogueService(session).require_active_customer_type(
            target_type
        )
        sites = list(
            await session.scalars(
                select(CustomerDeliverySite).where(
                    CustomerDeliverySite.customer_id == profile.id,
                    CustomerDeliverySite.is_active.is_(True),
                )
            )
        )
        if definition.requires_delivery_sites:
            # Conversion uses the registered address as its primary delivery site.
            # Validate it before creating any site; historical sites/orders stay intact.
            errors = FieldErrors()
            address = validate_address(
                Address(
                    line1=profile.address_line1 or "",
                    line2=profile.address_line2,
                    city=profile.address_city or "",
                    state=profile.address_state or "",
                    pincode=profile.address_pincode or "",
                    latitude=profile.address_latitude,
                    longitude=profile.address_longitude,
                    deliveryInstructions=profile.delivery_instructions,
                ),
                errors,
            )
            errors.raise_if_any()
            primary_sites = [site for site in sites if site.is_primary]
            if payload.delivery_address is not None:
                for site in primary_sites:
                    site.is_active = False
                    site.is_primary = False
                    site.updated_at = now
            if not primary_sites or payload.delivery_address is not None:
                session.add(
                    CustomerDeliverySite(
                        id=str(uuid4()),
                        customer_id=profile.id,
                        name="Primary site",
                        address_line1=address["line1"],
                        address_line2=address["line2"],
                        address_city=address["city"],
                        address_state=address["state"],
                        address_pincode=address["pincode"],
                        latitude=address["latitude"],
                        longitude=address["longitude"],
                        delivery_instructions=address["delivery_instructions"],
                        contact_name=profile.owner_name,
                        contact_mobile=profile.mobile_number,
                        is_primary=True,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
        else:
            for site in sites:
                site.is_active = False
                site.is_primary = False
                site.updated_at = now
        profile.customer_type = target_type
    profile.updated_at = now
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="CUSTOMER_UPDATED",
            actor_user_id=actor.user_id,
            entity_type="customer",
            entity_id=profile.id,
            message=f"Customer edited ({', '.join(sorted(changes))}): {payload.reason}"[:255],
            created_at=profile.updated_at,
        )
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    return await CustomerViewLoader(session).customer_view(profile)
