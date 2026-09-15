from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permissions.models import Permission


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_permissions(self) -> list[Permission]:
        result = await self.session.execute(select(Permission).order_by(Permission.module, Permission.action))
        return list(result.scalars().all())

    async def get_permission(self, permission_id: str) -> Permission | None:
        return await self.session.get(Permission, permission_id)
