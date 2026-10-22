"""Request and response models for customer registration, KYC review and documents.

Field names follow the mobile contract (spec §3.6, §3.7) rather than the database columns,
because these models *are* the contract the two apps were built against. The mapping between
them and the snake_case columns lives in `mapping.py`, in one place.

The existing onboarding schemas in `schemas.py` are untouched — the authentication and
onboarding-session contracts are frozen, and the app already ships against them.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.modules.customers.constants import (
    ApplicationStatus,
    DocumentStatus,
    PricingTier,
)
from app.shared.validation.names import check_name


def _as_utc(value: datetime) -> str:
    """Serialize MySQL's naive UTC datetimes unambiguously for JS clients."""
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[
    datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")
]


class Address(BaseModel):
    """Spec §3.1. Validated in `validators.validate_address`, not here.

    Pydantic would reject the whole body on the first bad field; the registration form needs
    every invalid field reported at once, so the real checks run in the service.
    """

    line1: str = Field(default="", max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str = Field(default="", max_length=120)
    state: str = Field(default="", max_length=120)
    pincode: str = Field(default="", max_length=12)


class DocumentSubmission(BaseModel):
    """One `{ type, number, fileName }` entry from the registration body (spec §5.1).

    `fileName` carries the `fileId` returned by the upload endpoint. The app reuses the
    field name it had when uploads were mocked, so the backend accepts either spelling.
    """

    type: str
    number: str = Field(max_length=40)
    file_name: str | None = Field(default=None, alias="fileName", max_length=80)
    file_id: str | None = Field(default=None, alias="fileId", max_length=80)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("type", mode="before")
    @classmethod
    def _document_code(cls, value) -> str:
        code = getattr(value, "value", value)
        code = str(code or "").strip().upper()
        if not code or len(code) > 40 or not code.replace("_", "").isalnum():
            raise ValueError("Enter a valid document type code.")
        return code

    @property
    def upload_id(self) -> str:
        return (self.file_id or self.file_name or "").strip()


class SiteSubmission(BaseModel):
    name: str = Field(default="", max_length=160)
    address: Address = Field(default_factory=Address)
    contact_name: str | None = Field(default=None, alias="contactName", max_length=160)
    contact_mobile: str | None = Field(default=None, alias="contactMobile", max_length=20)
    is_primary: bool | None = Field(default=None, alias="isPrimary")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", "contact_name", mode="after")
    @classmethod
    def _real_names(cls, value: str | None, info) -> str | None:
        """A site's own name and the person to ask for there, held to the same rule."""
        tidied = check_name(value, field=info.field_name, required=False)
        return tidied or None if value is not None else None



class CustomerRegistrationRequest(BaseModel):
    """Spec §5.1 / §7.1. The same body for both registration paths.

    `mobile` is present for the staff path, where the customer's number is typed in. On the
    self-registration path it is ignored unless it matches the verified number of the
    onboarding session — a customer can never register a number they did not verify.
    """

    customer_type: str = Field(alias="customerType")
    business_name: str = Field(default="", alias="businessName", max_length=160)
    owner_name: str = Field(default="", alias="ownerName", max_length=160)
    mobile: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    delivery_address: Address = Field(default_factory=Address, alias="deliveryAddress")
    documents: list[DocumentSubmission] = Field(default_factory=list)
    sites: list[SiteSubmission] = Field(default_factory=list)
    merchant_code: str | None = Field(default=None, alias="merchantCode", max_length=80)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("business_name", "owner_name", mode="after")
    @classmethod
    def _real_names(cls, value: str, info) -> str:
        """Refuse a name that is not a name in any language, and tidy the rest.

        Whether a *particular* name is required depends on the customer type and is decided by
        the registration rules; this only says that whatever was typed has to be a name. A
        customer registered as a run of `@` and `#` with no letter in it, and the only check
        in the way was `max_length`.
        """
        return check_name(value, field=info.field_name, required=False)

    @field_validator("customer_type", mode="before")
    @classmethod
    def _customer_type_code(cls, value) -> str:
        code = getattr(value, "value", value)
        code = str(code or "").strip().upper()
        if not code or len(code) > 40 or not code.replace("_", "").isalnum():
            raise ValueError("Enter a valid customer type code.")
        return code



class KycDocumentResponse(BaseModel):
    """Spec §3.4. `numberMasked` is the only form of the identifier that ever leaves here."""

    #: This document's own id, which is what the reveal route is addressed by. Without it a
    #: reviewer's screen has a masked number and no way to ask for the rest of it.
    id: str
    type: str
    number_masked: str = Field(alias="numberMasked")
    file_name: str = Field(alias="fileName")
    file_id: str | None = Field(default=None, alias="fileId")
    uploaded_at: UtcTime = Field(alias="uploadedAt")
    status: DocumentStatus

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class DeliverySiteResponse(BaseModel):
    id: str
    name: str
    address: Address
    contact_name: str | None = Field(default=None, alias="contactName")
    contact_mobile: str | None = Field(default=None, alias="contactMobile")
    is_primary: bool = Field(alias="isPrimary")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class CustomerResponse(BaseModel):
    """Spec §3.6, the shape both apps render a customer with."""

    id: str
    code: str | None = None
    customer_type: str | None = Field(default=None, alias="customerType")
    business_name: str | None = Field(default=None, alias="businessName")
    owner_name: str | None = Field(default=None, alias="ownerName")
    mobile: str
    email: str | None = None
    account_status: str = Field(alias="accountStatus")
    kyc_status: str = Field(alias="kycStatus")
    pricing_tier: PricingTier = Field(alias="pricingTier")
    delivery_address: Address = Field(alias="deliveryAddress")
    sites: list[DeliverySiteResponse] = Field(default_factory=list)
    documents: list[KycDocumentResponse] = Field(default_factory=list)
    gstin: str | None = None
    registered_at: UtcTime | None = Field(default=None, alias="registeredAt")
    approved_at: UtcTime | None = Field(default=None, alias="approvedAt")
    rejection_reason: str | None = Field(default=None, alias="rejectionReason")
    # Sum of open invoice balances. The invoice module does not exist yet, so this is 0 for
    # every customer; the field is present because the apps read it unconditionally.
    running_balance: int = Field(default=0, alias="runningBalance")
    last_order_at: UtcTime | None = Field(default=None, alias="lastOrderAt")
    # Credit terms are editable by authorised admin/merchant users, but read-only in the
    # customer app. Values are always returned so all three clients share one contract.
    credit_enabled: bool = Field(default=False, alias="creditEnabled")
    credit_limit: int = Field(default=0, alias="creditLimit")
    credit_days: int | None = Field(default=None, alias="creditDays")
    used_credit: int = Field(default=0, alias="usedCredit")
    available_credit: int = Field(default=0, alias="availableCredit")
    credit_active: bool = Field(default=False, alias="creditActive")
    application_id: str | None = Field(default=None, alias="applicationId")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class KycApplicationResponse(BaseModel):
    """Spec §3.7."""

    id: str
    customer_id: str = Field(alias="customerId")
    customer_type: str | None = Field(default=None, alias="customerType")
    business_name: str | None = Field(default=None, alias="businessName")
    owner_name: str | None = Field(default=None, alias="ownerName")
    mobile: str
    email: str | None = None
    documents: list[KycDocumentResponse] = Field(default_factory=list)
    delivery_address: Address = Field(alias="deliveryAddress")
    sites: list[DeliverySiteResponse] = Field(default_factory=list)
    status: ApplicationStatus
    submitted_at: UtcTime = Field(alias="submittedAt")
    reviewed_at: UtcTime | None = Field(default=None, alias="reviewedAt")
    reviewed_by: str | None = Field(default=None, alias="reviewedBy")
    rejection_reason: str | None = Field(default=None, alias="rejectionReason")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class DocumentUploadResponse(BaseModel):
    """Spec §17.1. Deliberately excludes the storage key and any physical path."""

    file_id: str = Field(alias="fileId")
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    size: int

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class DocumentUrlResponse(BaseModel):
    """Spec §17.2."""

    url: str
    expires_in_seconds: int = Field(alias="expiresInSeconds")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class EligibilityResponse(BaseModel):
    """Spec §7.4. `reasons` is empty when `eligible` is true."""

    eligible: bool
    reasons: list[str] = Field(default_factory=list)


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
    limit: int
    offset: int


class KycApplicationListResponse(BaseModel):
    items: list[KycApplicationResponse]
    total: int
    limit: int
    offset: int


class RegistrationProgressResponse(BaseModel):
    """What the Application Status screen needs, beyond the frozen onboarding status fields."""

    customer_id: str | None = Field(default=None, alias="customerId")
    code: str | None = None
    customer_type: str | None = Field(default=None, alias="customerType")
    account_status: str = Field(alias="accountStatus")
    kyc_status: str = Field(alias="kycStatus")
    profile_complete: bool = Field(alias="profileComplete")
    application_id: str | None = Field(default=None, alias="applicationId")
    application_status: str | None = Field(default=None, alias="applicationStatus")
    submitted_at: UtcTime | None = Field(default=None, alias="submittedAt")
    reviewed_at: UtcTime | None = Field(default=None, alias="reviewedAt")
    rejection_reason: str | None = Field(default=None, alias="rejectionReason")
    missing_fields: list[str] = Field(default_factory=list, alias="missingFields")
    missing_documents: list[str] = Field(default_factory=list, alias="missingDocumentTypes")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class RevealedDocumentNumber(BaseModel):
    """One document's identifier in full, for a reviewer comparing it with the scan.

    The only response in the project that carries an unmasked number. `numberMasked` comes back
    beside it so the screen can go straight back to hiding it without another call.
    """

    document_id: str = Field(alias="documentId")
    document_type: str = Field(alias="documentType")
    number: str
    number_masked: str = Field(alias="numberMasked")

    model_config = ConfigDict(populate_by_name=True)
