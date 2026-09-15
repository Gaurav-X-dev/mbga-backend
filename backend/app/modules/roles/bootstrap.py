from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.audit_logs.models import AuditLog
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole


class SuperAdminBootstrap:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def run(self) -> str:
        if not self.settings.rbac_bootstrap_super_admin_enabled:
            return "disabled"
        user = await self._find_target_user()
        role = await self._find_super_admin_role()
        if user is None:
            raise RuntimeError("Super Admin bootstrap target user was not found or was ambiguous")
        if role is None:
            raise RuntimeError("Super Admin role must be seeded before bootstrap")
        assigned = await self._assign_role(user, role)
        await self._audit(user, role, assigned)
        await self.session.commit()
        return f"{'created' if assigned else 'ready'}:{user.id}:{role.id}"

    async def _find_target_user(self) -> User | None:
        if self.settings.rbac_bootstrap_super_admin_user_id:
            return await self.session.get(User, self.settings.rbac_bootstrap_super_admin_user_id)
        if self.settings.rbac_bootstrap_super_admin_email:
            result = await self.session.execute(
                select(User).where(User.email == self.settings.rbac_bootstrap_super_admin_email.lower())
            )
            return result.scalar_one_or_none()
        if self.settings.rbac_bootstrap_super_admin_username:
            result = await self.session.execute(
                select(User).where(User.username == self.settings.rbac_bootstrap_super_admin_username.lower())
            )
            return result.scalar_one_or_none()
        if not self.settings.rbac_bootstrap_super_admin_mobile_number:
            return None
        stmt = select(User).where(
            User.mobile_number == self.settings.rbac_bootstrap_super_admin_mobile_number,
            User.country_code == self.settings.rbac_bootstrap_super_admin_country_code,
        )
        result = await self.session.execute(stmt)
        users = list(result.scalars().all())
        if len(users) != 1:
            return None
        return users[0]

    async def _find_super_admin_role(self) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.code == "super_admin", Role.is_active.is_(True)))
        return result.scalar_one_or_none()

    async def _assign_role(self, user: User, role: Role) -> bool:
        result = await self.session.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.scope_type == "global",
                UserRole.scope_id == "global",
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.valid_until = None
                return True
            return False
        now = datetime.now(UTC)
        self.session.add(
            UserRole(
                id=str(uuid4()),
                user_id=user.id,
                role_id=role.id,
                assigned_at=now,
                assigned_by=user.id,
                valid_from=now,
                valid_until=None,
                is_active=True,
                scope_type="global",
                scope_id="global",
            )
        )
        return True

    async def _audit(self, user: User, role: Role, changed: bool) -> None:
        self.session.add(
            AuditLog(
                id=str(uuid4()),
                event_type="super_admin.bootstrap",
                actor_user_id=user.id,
                entity_type="role",
                entity_id=role.id,
                message="Super Admin role assigned" if changed else "Super Admin role already assigned",
                created_at=datetime.now(UTC),
            )
        )
