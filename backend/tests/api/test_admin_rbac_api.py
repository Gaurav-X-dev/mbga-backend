import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.authentication.constants import LoginChannel
from app.modules.roles.router import get_role_service
from app.modules.roles.schemas import RoleCreate
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import get_effective_permission_service, require_authenticated_user
from app.shared.authorization.exceptions import AuthorizationDeniedError

pytestmark = pytest.mark.unit


class AllowPermissionService:
    async def require_permission(self, context, permission: str) -> None:
        return None


class DenyPermissionService:
    async def require_permission(self, context, permission: str) -> None:
        raise AuthorizationDeniedError()


class FakeRole:
    id = "role-1"
    name = "Ops"
    code = "ops"
    description = None
    is_system = False
    is_active = True


class FakeRoleService:
    def __init__(self) -> None:
        self.repository = self
        self.session = self

    async def create_role(self, payload: RoleCreate, actor_user_id=None):
        return FakeRole()

    async def commit(self):
        return None


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_admin_roles_unauthenticated_returns_401() -> None:
    clear_overrides()
    client = TestClient(app)

    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 401


def test_admin_roles_unauthorized_returns_403() -> None:
    clear_overrides()
    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext("u1", LoginChannel.ADMIN)
    app.dependency_overrides[get_effective_permission_service] = lambda: DenyPermissionService()
    client = TestClient(app)

    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 403
    clear_overrides()


def test_create_role_authorized_request_succeeds() -> None:
    clear_overrides()
    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext("u1", LoginChannel.ADMIN)
    app.dependency_overrides[get_effective_permission_service] = lambda: AllowPermissionService()
    app.dependency_overrides[get_role_service] = lambda: FakeRoleService()
    client = TestClient(app)

    response = client.post("/api/v1/admin/roles", json={"name": "Ops", "code": "ops"})

    assert response.status_code == 201
    assert response.json()["code"] == "ops"
    clear_overrides()


def test_privilege_escalation_payload_rejected_by_api() -> None:
    clear_overrides()
    app.dependency_overrides[require_authenticated_user] = lambda: AuthContext("u1", LoginChannel.ADMIN)
    app.dependency_overrides[get_effective_permission_service] = lambda: AllowPermissionService()
    app.dependency_overrides[get_role_service] = lambda: FakeRoleService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/roles",
        json={"name": "Ops", "code": "ops", "permissions": ["roles.delete"]},
    )

    assert response.status_code == 422
    clear_overrides()
