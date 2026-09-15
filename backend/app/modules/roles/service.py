from app.modules.roles.exceptions import LastSuperAdminError, ProtectedSystemRoleError, RoleAlreadyExistsError
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
        await self.repository.replace_role_permissions(
            role_id=role_id,
            permission_ids=permission_ids,
            actor_user_id=actor_user_id,
        )
