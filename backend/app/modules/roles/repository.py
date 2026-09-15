from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.models import Role, RoleLoginChannel, RolePermission, RoleType
from app.modules.roles.schemas import RoleCreate, RoleUpdate


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_roles(self) -> list[Role]:
        result = await self.session.execute(select(Role).order_by(Role.code))
        return list(result.scalars().all())

    async def get_role(self, role_id: str) -> Role | None:
        return await self.session.get(Role, role_id)

    async def get_by_code(self, code: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.code == code))
        return result.scalar_one_or_none()

    async def create_role(self, payload: RoleCreate, actor_user_id: str | None = None) -> Role:
        now = datetime.now(UTC)
        role = Role(
            id=str(uuid4()),
            name=payload.name,
            code=payload.code.lower(),
            description=payload.description,
            role_type=RoleType.CUSTOM,
            is_system=False,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self.session.add(role)
        return role

    async def update_role(self, role: Role, payload: RoleUpdate, actor_user_id: str | None = None) -> Role:
        if payload.name is not None:
            role.name = payload.name
        if payload.description is not None:
            role.description = payload.description
        if payload.is_active is not None:
            role.is_active = payload.is_active
        role.updated_at = datetime.now(UTC)
        role.updated_by = actor_user_id
        return role

    async def replace_role_permissions(
        self,
        *,
        role_id: str,
        permission_ids: list[str],
        actor_user_id: str | None = None,
    ) -> None:
        role = await self.get_role(role_id)
        if role is None:
            return
        role.permissions.clear()
        now = datetime.now(UTC)
        for permission_id in dict.fromkeys(permission_ids):
            role.permissions.append(
                RolePermission(role_id=role_id, permission_id=permission_id, granted_at=now, granted_by=actor_user_id)
            )

    async def set_role_channels(
        self,
        *,
        role_id: str,
        channels: dict[str, bool],
        actor_user_id: str | None = None,
    ) -> None:
        role = await self.get_role(role_id)
        if role is None:
            return
        role.login_channels.clear()
        now = datetime.now(UTC)
        for channel, is_allowed in channels.items():
            role.login_channels.append(
                RoleLoginChannel(
                    role_id=role_id,
                    login_channel=channel,
                    is_allowed=is_allowed,
                    created_at=now,
                    created_by=actor_user_id,
                )
            )
