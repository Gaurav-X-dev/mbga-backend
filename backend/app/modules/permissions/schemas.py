from pydantic import BaseModel


class PermissionResponse(BaseModel):
    id: str
    name: str
    code: str
    module: str
    action: str
    description: str | None = None
    is_system: bool
    is_active: bool


class PermissionListResponse(BaseModel):
    items: list[PermissionResponse]
    total: int
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class PermissionGroupResponse(BaseModel):
    module: str
    permissions: list[PermissionResponse]


class PermissionGroupedResponse(BaseModel):
    groups: list[PermissionGroupResponse]
    total: int
