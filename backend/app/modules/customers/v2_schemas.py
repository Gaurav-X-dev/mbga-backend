"""Request and response contracts for customer registration v2 only."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.customers.business_schemas import Address, SiteSubmission


class DocumentSide(StrEnum):
    FRONT = "FRONT"
    BACK = "BACK"
    PAGE_1 = "PAGE_1"
    PAGE_2 = "PAGE_2"


class UploadSource(StrEnum):
    CAMERA = "CAMERA"
    GALLERY = "GALLERY"
    FILE_PICKER = "FILE_PICKER"


class DocumentFileSubmissionV2(BaseModel):
    file_id: str = Field(alias="fileId", min_length=1, max_length=80)
    file_name: str | None = Field(default=None, alias="fileName", max_length=180)
    file_size: int | None = Field(default=None, alias="fileSize", ge=0)
    side: DocumentSide = DocumentSide.FRONT
    source: UploadSource = UploadSource.FILE_PICKER

    model_config = ConfigDict(populate_by_name=True)


class DocumentSubmissionV2(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    number: str = Field(max_length=40)
    files: list[DocumentFileSubmissionV2] = Field(min_length=1, max_length=2)
    # Accepted only for compatibility with the already-built frontend. `files` remains the
    # canonical value and conflicting duplicates are rejected.
    file_id: str | None = Field(default=None, alias="fileId", max_length=80)
    file_ids: list[str] | None = Field(default=None, alias="fileIds", max_length=2)
    file_name: str | None = Field(default=None, alias="fileName", max_length=180)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        code = getattr(value, "value", value)
        code = str(code or "").strip().upper()
        if not code or len(code) > 40 or not code.replace("_", "").isalnum():
            raise ValueError("Enter a valid document type code.")
        return code

    @model_validator(mode="after")
    def duplicated_legacy_fields_must_match(self):
        ids = [item.file_id for item in self.files]
        if self.file_id is not None and self.file_id != ids[0]:
            raise ValueError("fileId must match the first item in files")
        if self.file_ids is not None and self.file_ids != ids:
            raise ValueError("fileIds must match files in the same order")
        return self


class CustomerProfileV2Payload(BaseModel):
    mobile_number: str | None = None
    merchant_code: str = Field(min_length=1, max_length=80)
    customer_type: str | None = Field(
        default=None, validation_alias=AliasChoices("customer_type", "customerType")
    )
    name: str | None = Field(default=None, min_length=2, max_length=160)
    gst_number: str | None = Field(default=None, max_length=30)
    owner_name: str | None = Field(
        default=None, validation_alias=AliasChoices("owner_name", "ownerName"), max_length=160
    )
    email: str | None = Field(default=None, max_length=255)
    delivery_address: Address | None = Field(
        default=None, validation_alias=AliasChoices("delivery_address", "deliveryAddress")
    )
    documents: list[DocumentSubmissionV2] | None = None
    sites: list[SiteSubmission] | None = None
    business_name: str | None = Field(
        default=None, validation_alias=AliasChoices("business_name", "businessName"), max_length=160
    )
    mobile: str | None = Field(default=None, max_length=20)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("customer_type", mode="before")
    @classmethod
    def normalize_customer_type(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class CustomerProfileV2Update(BaseModel):
    merchant_code: str | None = Field(default=None, min_length=1, max_length=80)
    customer_type: str | None = Field(
        default=None, validation_alias=AliasChoices("customer_type", "customerType")
    )
    name: str | None = Field(default=None, min_length=2, max_length=160)
    gst_number: str | None = Field(default=None, max_length=30)
    owner_name: str | None = Field(
        default=None, validation_alias=AliasChoices("owner_name", "ownerName"), max_length=160
    )
    email: str | None = Field(default=None, max_length=255)
    delivery_address: Address | None = Field(
        default=None, validation_alias=AliasChoices("delivery_address", "deliveryAddress")
    )
    documents: list[DocumentSubmissionV2] | None = None
    sites: list[SiteSubmission] | None = None
    business_name: str | None = Field(
        default=None, validation_alias=AliasChoices("business_name", "businessName"), max_length=160
    )
    mobile: str | None = Field(default=None, max_length=20)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("customer_type", mode="before")
    @classmethod
    def normalize_customer_type(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class DocumentUploadResponseV2(BaseModel):
    file_id: str = Field(alias="fileId")
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    size: int
    side: DocumentSide
    source: UploadSource
    uploaded_at: datetime = Field(alias="uploadedAt")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class DocumentFileResponseV2(BaseModel):
    file_id: str = Field(alias="fileId")
    file_name: str = Field(alias="fileName")
    file_size: int = Field(alias="fileSize")
    content_type: str = Field(alias="contentType")
    side: DocumentSide
    source: UploadSource
    sort_order: int = Field(alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class KycDocumentRequirementV2(BaseModel):
    type: str
    label: str
    required: bool
    required_group: str | None = Field(default=None, alias="requiredGroup")
    number_format: str = Field(alias="numberFormat")
    min_files: int = Field(default=1, alias="minFiles")
    max_files: int = Field(default=2, alias="maxFiles")
    allowed_sides: list[DocumentSide] = Field(alias="allowedSides")
    allowed_mime_types: list[str] = Field(alias="allowedMimeTypes")
    max_size_bytes: int = Field(alias="maxSizeBytes")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class KycRequirementsResponseV2(BaseModel):
    customer_type: str = Field(alias="customerType")
    minimum_documents: int = Field(alias="minimumDocuments")
    documents: list[KycDocumentRequirementV2]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def utc_now() -> datetime:
    return datetime.now(UTC)
