from datetime import datetime

from pydantic import BaseModel, Field


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


class RegistrationFieldsResponse(BaseModel):
    fields: list[RegistrationField]


class CustomerProfilePayload(BaseModel):
    mobile_number: str
    merchant_code: str | None = None
    customer_type: str | None = None
    name: str | None = None
    gst_number: str | None = None


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
    created_at: datetime
    updated_at: datetime


class RegistrationStatusResponse(BaseModel):
    status: str
    message: str
