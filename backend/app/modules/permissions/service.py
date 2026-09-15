from app.modules.permissions.models import Permission
from app.modules.permissions.repository import PermissionRepository


class PermissionService:
    def __init__(self, repository: PermissionRepository) -> None:
        self.repository = repository

    async def list_permissions(self) -> list[Permission]:
        return await self.repository.list_permissions()

    async def get_permission(self, permission_id: str) -> Permission | None:
        return await self.repository.get_permission(permission_id)
