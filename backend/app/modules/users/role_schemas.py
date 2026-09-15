from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserRoleAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scope_type: str = Field(default="global", min_length=1, max_length=50)
    scope_id: str = Field(default="global", min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_window(self) -> "UserRoleAssignment":
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class UserRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scope_type: str | None = Field(default=None, min_length=1, max_length=50)
    scope_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_window(self) -> "UserRoleUpdate":
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class UserRoleResponse(BaseModel):
    id: str
    user_id: str
    role_id: str
    role_code: str | None = None
    assigned_at: datetime
    assigned_by: str | None = None
    is_active: bool
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scope_type: str = "global"
    scope_id: str = "global"


class EffectivePermissionsResponse(BaseModel):
    user_id: str
    login_channel: str
    permissions: list[str]


class AllowedChannelsResponse(BaseModel):
    user_id: str
    channels: list[str]
