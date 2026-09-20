from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class DeliveryUserType(StrEnum):
    DRIVER = "DRIVER"
    HELPER = "HELPER"


class DeliveryUserCreate(BaseModel):
    delivery_user_type: DeliveryUserType
    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    employee_code: str = Field(min_length=2, max_length=80)
    driving_license_number: str | None = Field(default=None, max_length=80)
    driving_license_expiry: date | None = None
    address: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_driver_fields(self):
        if self.delivery_user_type == DeliveryUserType.DRIVER:
            if not self.driving_license_number or not self.driving_license_expiry:
                raise ValueError("Driver requires driving license number and expiry")
            if self.driving_license_expiry <= date.today():
                raise ValueError("Driving license expiry must be in the future")
        return self


class DeliveryUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    employee_code: str | None = Field(default=None, min_length=2, max_length=80)
    driving_license_number: str | None = Field(default=None, max_length=80)
    driving_license_expiry: date | None = None
    address: str | None = Field(default=None, max_length=255)


class DeliveryUserResponse(BaseModel):
    id: str
    merchant_id: str
    user_id: str
    delivery_user_type: str
    full_name: str | None = None
    mobile_number: str | None = None
    email: str | None = None
    employee_code: str | None = None
    driving_license_number: str | None = None
    driving_license_expiry: datetime | None = None
    address: str | None = None
    status: str
    approval_status: str
    role: str
    allowed_channel: str = "DELIVERY"
    created_at: datetime


class DeliveryUserListResponse(BaseModel):
    items: list[DeliveryUserResponse]
    total: int
    limit: int
    offset: int
