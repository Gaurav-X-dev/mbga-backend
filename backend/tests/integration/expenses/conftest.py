"""Fixtures for the expenses slice.

Reuses the authentication suite's database, migration and environment fixtures, the way the
customer and pricing suites do. That conftest is imported here, never edited.
"""

from uuid import uuid4

import pytest

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

MERCHANT = "/api/v1/merchant"
MERCHANT_AUTH = "/api/v1/merchant/auth"
EXPENSES = f"{MERCHANT}/expenses"
CATEGORIES = f"{EXPENSES}/categories"

#: The starting set every merchant is seeded with, in picker order.
DEFAULT_CODES = ["FUEL", "VEHICLE_MAINTENANCE", "SALARY", "RENT", "UTILITIES", "MISCELLANEOUS"]


@pytest.fixture
def settings_overrides() -> dict:
    return {}


async def expense_staff(
    auth_env,
    merchant=None,
    permissions: tuple[str, ...] = ("expenses.view", "expenses.manage"),
):
    """Merchant staff holding the expense permissions. Returns (token, merchant, user).

    Granted through a throwaway role rather than by widening `manager`, because the seed
    deliberately leaves expenses unmapped and the RBAC suite asserts that.
    """
    role = f"expense_staff_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def put(auth_env, path: str, token: str, json: dict | None = None):
    return await auth_env.client.put(path, json=json, headers={"Authorization": f"Bearer {token}"})


async def patch(auth_env, path: str, token: str, json: dict | None = None):
    return await auth_env.client.patch(path, json=json, headers={"Authorization": f"Bearer {token}"})


async def delete(auth_env, path: str, token: str):
    return await auth_env.client.delete(path, headers={"Authorization": f"Bearer {token}"})


async def categories(auth_env, token: str) -> list[dict]:
    """The merchant's category list, seeding the starting set on first call."""
    response = await auth_env.get(CATEGORIES, token)
    assert response.status_code == 200, response.text
    return response.json()


async def category_id(auth_env, token: str, code: str = "FUEL") -> str:
    for item in await categories(auth_env, token):
        if item["code"] == code:
            return item["id"]
    raise AssertionError(f"category {code} is not in the seeded list")


async def add_expense(auth_env, token: str, **overrides):
    """Create one expense. Returns the raw response so a test can assert on failures too."""
    body = {"amount": 4200, "note": "Diesel - MP09 GH 4521", **overrides}
    if "categoryId" not in body and "category" not in body:
        body["categoryId"] = await category_id(auth_env, token)
    return await auth_env.post(EXPENSES, token, json=body)


async def created_expense(auth_env, token: str, **overrides) -> dict:
    response = await add_expense(auth_env, token, **overrides)
    assert response.status_code == 201, response.text
    return response.json()
