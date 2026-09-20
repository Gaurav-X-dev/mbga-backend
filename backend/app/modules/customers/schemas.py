from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.modules.authentication.account_state import NextAction


class CustomerType(StrEnum):
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"


def _upper(value):
    return value.strip().upper() if isinstance(value, str) else value


class CheckMobileRequest(BaseModel):
    mobile_number: str = Field(min_length=6, max_length=20)


class CheckMobileResponse(BaseModel):
    code: str
    message: str
    registered: bool
    registration_allowed: bool = False


class RegistrationField(BaseModel):
    api_field_name: str
    display_label: str
    data_type: str
    required: bool
    source: str
    allowed_values: list[str] | None = None
    required_for: str = Field(default="submit", description="`create` (needed to save the draft) or `submit` (needed before review).")


class RegistrationFieldsResponse(BaseModel):
    fields: list[RegistrationField]


class CustomerProfilePayload(BaseModel):
    mobile_number: str | None = Field(
        default=None,
        description="Optional. The number always comes from the onboarding session; a different number is rejected.",
    )
    merchant_code: str = Field(min_length=1, max_length=80)
    customer_type: CustomerType | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    gst_number: str | None = Field(default=None, max_length=30)

    _normalize_type = field_validator("customer_type", mode="before")(_upper)
    _normalize_code = field_validator("merchant_code", mode="before")(_upper)


class CustomerProfileUpdate(BaseModel):
    merchant_code: str | None = Field(default=None, min_length=1, max_length=80)
    customer_type: CustomerType | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    gst_number: str | None = Field(default=None, max_length=30)

    _normalize_type = field_validator("customer_type", mode="before")(_upper)
    _normalize_code = field_validator("merchant_code", mode="before")(_upper)


class CustomerProfileResponse(BaseModel):
    id: str
    mobile_number: str
    merchant_id: str | None = None
    merchant_code: str | None = None
    customer_type: str | None = None
    name: str | None = None
    gst_number: str | None = None
    status: str
    rejection_reason: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RegistrationStatusResponse(BaseModel):
    status: str = Field(description="NOT_STARTED, PROFILE_INCOMPLETE, DOCUMENTS_PENDING, UNDER_REVIEW, APPROVED, REJECTED or SUSPENDED.")
    message: str
    next_action: NextAction | None = None
    rejection_reason: str | None = None


class CustomerRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CustomerReviewListResponse(BaseModel):
    items: list[CustomerProfileResponse]
