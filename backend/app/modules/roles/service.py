from sqlalchemy import select

from app.modules.permissions.catalogue import expand
from app.modules.permissions.models import Permission
from app.modules.roles.exceptions import (
    LastSuperAdminError,
    ProtectedSystemRoleError,
    RoleAlreadyExistsError,
)
from app.modules.roles.models import Role
from app.modules.roles.repository import RoleRepository
from app.modules.roles.schemas import RoleCreate, RoleUpdate


class RoleService:
    def __init__(self, repository: RoleRepository) -> None:
        self.repository = repository

    async def list_roles(self) -> list[Role]:
        return await self.repository.list_roles()

    async def create_role(self, payload: RoleCreate, actor_user_id: str | None = None) -> Role:
        if await self.repository.get_by_code(payload.code.lower()):
            raise RoleAlreadyExistsError()
        return await self.repository.create_role(payload, actor_user_id)

    async def update_role(self, role_id: str, payload: RoleUpdate, actor_user_id: str | None = None) -> Role | None:
        role = await self.repository.get_role(role_id)
        if role is None:
            return None
        return await self.repository.update_role(role, payload, actor_user_id)

    async def delete_role(self, role_id: str) -> None:
        role = await self.repository.get_role(role_id)
        if role and role.is_system:
            raise ProtectedSystemRoleError()
        if role:
            await self.repository.session.delete(role)

    def ensure_not_last_super_admin(self, *, role_code: str, active_super_admin_count: int) -> None:
        if role_code == "super_admin" and active_super_admin_count <= 1:
            raise LastSuperAdminError()

    async def replace_permissions(self, role_id: str, permission_ids: list[str], actor_user_id: str | None = None) -> None:
        """Save a role's permissions, together with everything they cannot be used without.

        Ticking "Create users" and getting no Users screen was the single most common
        complaint about the Permission Matrix: the list behind the button needs `users.view`,
        and the operator had no way to know that. So the ticked set is expanded here, once,
        where every caller passes - the panel, the API and any script.

        Expanding on save rather than at check time is deliberate. The stored rows then *are*
        the answer: the matrix shows what the role really carries, an audit of the table reads
        true, and nothing has to re-derive the same rule in a second place and drift from it.

        Only reading rights are ever added; see `catalogue.dependencies_for`.
        """
        permissions = await self.repository.session.scalars(select(Permission))
        by_id = {permission.id: permission.code for permission in permissions}
        known = set(by_id.values())
        by_code = {code: permission_id for permission_id, code in by_id.items()}

        chosen = {by_id[pid] for pid in permission_ids if pid in by_id}
        expanded = expand(chosen, known)

        # The operator's own choices stay in the order they were made, and the dependencies
        # that had to be added follow them, so the audit trail reads as what was decided plus
        # what that decision required.
        ordered = [pid for pid in dict.fromkeys(permission_ids) if pid in by_id]
        ordered += [by_code[code] for code in sorted(expanded - chosen)]

        await self.repository.replace_role_permissions(
            role_id=role_id,
            permission_ids=ordered,
            actor_user_id=actor_user_id,
        )
