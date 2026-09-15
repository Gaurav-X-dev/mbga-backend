from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RoleLoginChannel, RolePermission, RoleType
from app.modules.roles.seeds import SEED_PERMISSIONS, SEED_ROLES


class RBACSeedRunner:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> dict[str, int]:
        roles_created = await self._seed_roles()
        permissions_created = await self._seed_permissions()
        channels_created = await self._seed_role_channels()
        super_admin_permissions_created = await self._seed_super_admin_permissions()
        await self.session.commit()
        return {
            "roles_created": roles_created,
            "permissions_created": permissions_created,
            "channels_created": channels_created,
            "super_admin_permissions_created": super_admin_permissions_created,
        }

    async def _seed_roles(self) -> int:
        created = 0
        now = datetime.now(UTC)
        for seed in SEED_ROLES:
            existing = await self._get_role(seed.code)
            if existing:
                continue
            self.session.add(
                Role(
                    id=str(uuid4()),
                    name=seed.name,
                    code=seed.code,
                    description=f"System role: {seed.name}",
                    role_type=RoleType.SYSTEM,
                    is_system=True,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                    created_by=None,
                    updated_by=None,
                )
            )
            created += 1
        return created

    async def _seed_permissions(self) -> int:
        created = 0
        now = datetime.now(UTC)
        for seed in SEED_PERMISSIONS:
            existing = await self._get_permission(seed.code)
            if existing:
                continue
            self.session.add(
                Permission(
                    id=str(uuid4()),
                    name=seed.name,
                    code=seed.code,
                    module=seed.module,
                    action=seed.action,
                    description=f"System permission: {seed.name}",
                    is_system=True,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        return created

    async def _seed_role_channels(self) -> int:
        created = 0
        now = datetime.now(UTC)
        await self.session.flush()
        for seed in SEED_ROLES:
            role = await self._get_role(seed.code)
            if role is None:
                continue
            for channel in seed.channels:
                existing = await self.session.get(RoleLoginChannel, {"role_id": role.id, "login_channel": channel.value})
                if existing:
                    continue
                self.session.add(
                    RoleLoginChannel(
                        role_id=role.id,
                        login_channel=channel.value,
                        is_allowed=True,
                        created_at=now,
                        created_by=None,
                    )
                )
                created += 1
        return created

    async def _seed_super_admin_permissions(self) -> int:
        role = await self._get_role("super_admin")
        if role is None:
            return 0
        await self.session.flush()
        result = await self.session.execute(select(Permission))
        permissions = list(result.scalars().all())
        created = 0
        now = datetime.now(UTC)
        for permission in permissions:
            existing = await self.session.get(
                RolePermission,
                {"role_id": role.id, "permission_id": permission.id},
            )
            if existing:
                continue
            self.session.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id,
                    granted_at=now,
                    granted_by=None,
                )
            )
            created += 1
        return created

    async def _get_role(self, code: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.code == code))
        return result.scalar_one_or_none()

    async def _get_permission(self, code: str) -> Permission | None:
        result = await self.session.execute(select(Permission).where(Permission.code == code))
        return result.scalar_one_or_none()
