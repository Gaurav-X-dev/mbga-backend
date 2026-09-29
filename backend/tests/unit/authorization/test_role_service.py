import pytest
from pydantic import ValidationError

from app.modules.roles.exceptions import (
    LastSuperAdminError,
    ProtectedSystemRoleError,
    RoleAlreadyExistsError,
)
from app.modules.roles.schemas import RoleCreate
from app.modules.roles.service import RoleService

pytestmark = pytest.mark.unit


class FakeRole:
    def __init__(self, is_system: bool = False) -> None:
        self.is_system = is_system


class FakeRoleRepository:
    def __init__(self, existing: bool = False, role: FakeRole | None = None) -> None:
        self.existing = existing
        self.role = role
        self.created = False
        self.session = self

    async def get_by_code(self, code: str):
        return FakeRole() if self.existing else None

    async def create_role(self, payload, actor_user_id=None):
        self.created = True
        return FakeRole()

    async def get_role(self, role_id: str):
        return self.role

    async def delete(self, role):
        self.role = None


@pytest.mark.asyncio
async def test_duplicate_role_code_rejected() -> None:
    service = RoleService(FakeRoleRepository(existing=True))

    with pytest.raises(RoleAlreadyExistsError):
        await service.create_role(RoleCreate(name="Manager", code="manager"))


@pytest.mark.asyncio
async def test_creating_dynamic_role() -> None:
    repo = FakeRoleRepository()
    service = RoleService(repo)

    await service.create_role(RoleCreate(name="Custom Ops", code="custom_ops"))

    assert repo.created is True


@pytest.mark.asyncio
async def test_protected_system_role_delete_rejected() -> None:
    service = RoleService(FakeRoleRepository(role=FakeRole(is_system=True)))

    with pytest.raises(ProtectedSystemRoleError):
        await service.delete_role("role-1")


def test_last_super_admin_protection() -> None:
    service = RoleService(FakeRoleRepository())

    with pytest.raises(LastSuperAdminError):
        service.ensure_not_last_super_admin(role_code="super_admin", active_super_admin_count=1)


def test_privilege_escalation_payload_rejected() -> None:
    with pytest.raises(ValidationError):
        RoleCreate(name="Ops", code="ops", permissions=["roles.delete"])
