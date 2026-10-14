import pytest

from app.main import app
from tests.integration.deliveries.conftest import ready_to_dispatch

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
MERCHANT_AUTH = "/api/v1/merchant/auth"


async def _admin_token(env) -> str:
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def test_admin_order_copy_requires_explicit_merchant_scope(env):
    _staff, merchant, order, _slip, _driver = await ready_to_dispatch(env)
    token = await _admin_token(env)

    missing_scope = await env.get("/api/v1/admin/orders", token)
    selected_scope = await env.get(
        f"/api/v1/admin/orders?merchantId={merchant.id}", token
    )

    assert missing_scope.status_code == 422
    assert selected_scope.status_code == 200, selected_scope.text
    assert order["id"] in {row["id"] for row in selected_scope.json()}


async def test_admin_scope_never_leaks_another_merchants_order(env):
    _staff_a, merchant_a, _order_a, _slip_a, _driver_a = await ready_to_dispatch(env)
    _staff_b, _merchant_b, order_b, _slip_b, _driver_b = await ready_to_dispatch(env)
    token = await _admin_token(env)

    response = await env.get(
        f"/api/v1/admin/orders/{order_b['id']}?merchantId={merchant_a.id}", token
    )

    assert response.status_code == 404


async def test_merchant_session_cannot_call_admin_copy(env):
    merchant_token, merchant, _order, _slip, _driver = await ready_to_dispatch(env)

    response = await env.get(
        f"/api/v1/admin/orders?merchantId={merchant.id}",
        merchant_token,
    )

    assert response.status_code == 403


async def test_admin_can_read_each_selected_merchant_module(env):
    _merchant_token, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    token = await _admin_token(env)

    for path in ("expenses", "inventory", "deliveries", "tasks", "team"):
        response = await env.get(
            f"/api/v1/admin/{path}?merchantId={merchant.id}", token
        )
        assert response.status_code == 200, f"{path}: {response.text}"


async def test_admin_can_read_every_new_selected_merchant_module(env):
    _merchant_token, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    token = await _admin_token(env)

    paths = (
        "customers",
        "invoices",
        "payments",
        "pricing/months",
        "pricing/change-logs",
        "delivery-users",
        "delivery-users/available",
        "vehicles",
        "vehicles/available",
    )
    for path in paths:
        response = await env.get(
            f"/api/v1/admin/{path}?merchantId={merchant.id}", token
        )
        assert response.status_code == 200, f"{path}: {response.text}"


async def test_new_admin_modules_require_merchant_scope(env):
    token = await _admin_token(env)

    for path in ("customers", "invoices", "payments", "pricing/months", "delivery-users", "vehicles"):
        response = await env.get(f"/api/v1/admin/{path}", token)
        assert response.status_code == 422, f"{path}: {response.text}"


def test_admin_and_merchant_transactional_routes_have_method_parity():
    paths = app.openapi()["paths"]
    verbs = {"get", "post", "patch", "delete"}
    groups = ("/orders", "/expenses", "/inventory", "/deliveries", "/tasks", "/team")

    def operations(prefix: str) -> set[tuple[str, str]]:
        return {
            (verb, path.removeprefix(prefix))
            for path, item in paths.items()
            if path.startswith(prefix)
            and any(path.startswith(f"{prefix}{group}") for group in groups)
            for verb in item
            if verb in verbs
        }

    assert operations("/api/v1/admin") == operations("/api/v1/merchant")

    for path, item in paths.items():
        if not any(path.startswith(f"/api/v1/admin{group}") for group in groups):
            continue
        for verb, operation in item.items():
            if verb not in verbs:
                continue
            merchant_id = [
                parameter
                for parameter in operation.get("parameters", [])
                if parameter["name"] == "merchantId"
            ]
            assert merchant_id and merchant_id[0]["required"] is True, (verb, path)


def test_every_non_auth_merchant_operation_has_an_admin_counterpart():
    paths = app.openapi()["paths"]
    verbs = {"get", "post", "put", "patch", "delete"}

    def operations(prefix: str) -> set[tuple[str, str]]:
        return {
            (verb, path.removeprefix(prefix))
            for path, item in paths.items()
            if path.startswith(f"{prefix}/") and not path.startswith(f"{prefix}/auth")
            for verb in item
            if verb in verbs
        }

    merchant_operations = operations("/api/v1/merchant")
    admin_operations = operations("/api/v1/admin")

    # Bumped with each merchant operation added, deliberately: the number is the tripwire
    # that makes somebody check the admin side has kept up.
    assert len(merchant_operations) == 103
    assert merchant_operations <= admin_operations
