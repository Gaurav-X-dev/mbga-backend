from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.authentication.constants import LoginChannel


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    description: str | None = None


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class RoleResponse(BaseModel):
    id: str
    name: str
    code: str
    description: str | None = None
    is_system: bool
    is_active: bool


class RoleListResponse(BaseModel):
    items: list[RoleResponse]
    total: int
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class RolePermissionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_ids: list[str] = Field(default_factory=list)


class RoleChannelAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_channel: LoginChannel
    is_allowed: bool = True


class RoleChannelListAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[RoleChannelAssignment]


class RoleChannelResponse(BaseModel):
    login_channel: LoginChannel
    is_allowed: bool
    created_at: datetime | None = None
