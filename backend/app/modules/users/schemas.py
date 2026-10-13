from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    #: The agency this person works for. **Required for a merchant's staff**, because a role on
    #: its own does not make somebody part of an agency: the team list, the task picker and
    #: every merchant-scoped screen read the `merchant_users` link, not the role. A salesperson
    #: created without this had the role and appeared on none of them, with no error to say so.
    #:
    #: Left out for a platform user - a super admin belongs to no agency.
    merchant_id: str | None = Field(default=None, alias="merchantId", max_length=36)
    #: The job title the office calls them, shown wherever staff are listed. Defaults to the
    #: role's own name. Ignored without `merchantId`.
    staff_type: str | None = Field(default=None, alias="staffType", max_length=60)

    model_config = ConfigDict(populate_by_name=True)


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
