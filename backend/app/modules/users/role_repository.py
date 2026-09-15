from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RoleLoginChannel, RolePermission
from app.modules.users.models import User
from app.modules.users.role_models import UserRole


class UserRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_effective_permissions(
        self,
        *,
        user_id: str,
        login_channel: LoginChannel,
        now: datetime,
    ) -> set[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(User, User.id == UserRole.user_id)
            .join(RoleLoginChannel, RoleLoginChannel.role_id == Role.id)
            .where(User.id == user_id)
            .where(User.status == "ACTIVE")
            .where(UserRole.is_active.is_(True))
            .where((UserRole.valid_from.is_(None)) | (UserRole.valid_from <= now))
            .where((UserRole.valid_until.is_(None)) | (UserRole.valid_until > now))
            .where(Role.is_active.is_(True))
            .where(Permission.is_active.is_(True))
            .where(RoleLoginChannel.login_channel == login_channel.value)
            .where(RoleLoginChannel.is_allowed.is_(True))
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())
