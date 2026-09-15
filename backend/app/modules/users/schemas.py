from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserSummary(BaseModel):
    id: str
    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    mobile_number: str | None = None
    country_code: str | None = None
    role: str
    status: str
    created_at: datetime | None = None


class UserCreate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    full_name: str | None = Field(default=None, max_length=160)
    mobile_number: str | None = Field(default=None, max_length=15)
    country_code: str | None = Field(default="+91", max_length=5)
    role: str = "admin_user"
    status: str = "ACTIVE"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    full_name: str | None = Field(default=None, max_length=160)
    mobile_number: str | None = Field(default=None, max_length=15)
    country_code: str | None = Field(default=None, max_length=5)
    status: str | None = None


class UserListResponse(BaseModel):
    items: list[UserSummary]
    total: int
    limit: int
    offset: int


class EffectivePermissionsResponse(BaseModel):
    user_id: str
    permissions: list[str]
