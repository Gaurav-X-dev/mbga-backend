from datetime import datetime

from pydantic import BaseModel, Field


class MerchantCreate(BaseModel):
    merchant_code: str = Field(min_length=2, max_length=80)
    business_name: str = Field(min_length=2, max_length=160)
    contact_person_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    gst_number: str | None = Field(default=None, max_length=30)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)


class MerchantUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    contact_person_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    gst_number: str | None = Field(default=None, max_length=30)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)


class MerchantResponse(BaseModel):
    id: str
    merchant_code: str
    business_name: str
    contact_person_name: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    gst_number: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    primary_user_id: str | None = None
    status: str
    approval_status: str
    role: str = "manager"
    allowed_channel: str = "MERCHANT"
    created_at: datetime


class MerchantListResponse(BaseModel):
    items: list[MerchantResponse]
    total: int
    limit: int
    offset: int


class MerchantUserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    staff_type: str = Field(default="MANAGER", max_length=60)


class MerchantUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    staff_type: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=30)


class MerchantUserResponse(BaseModel):
    id: str
    merchant_id: str
    user_id: str
    full_name: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    staff_type: str | None = None
    status: str
    created_at: datetime
