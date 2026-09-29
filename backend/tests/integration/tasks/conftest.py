"""Fixtures for the task slice.

Reuses the authentication suite's database, migration and environment fixtures, the way every
other suite does. That conftest is imported here, never edited.

A task test almost always needs two or three staff members - somebody to create, somebody to
assign to, somebody to mention - so `team_of()` builds a whole crew in one call.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.shared.date_time.business_calendar import business_today

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
MERCHANT_AUTH = f"{MERCHANT}/auth"
TASKS = f"{MERCHANT}/tasks"
TEAM = f"{MERCHANT}/team"
DOCUMENTS = f"{MERCHANT}/documents"

FULL = ("tasks.view",)


@pytest.fixture
def settings_overrides() -> dict:
    """Required by the shared `env` fixture; tasks need no setting changed."""
    return {}


async def task_staff(auth_env, merchant=None, permissions: tuple[str, ...] = FULL, name: str = "Test Manager"):
    """Merchant staff holding `tasks.view`. Returns (token, merchant, user)."""
    role = f"tasks_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    if name != "Test Manager":
        await _rename(auth_env, user.id, name)
        user.full_name = name
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def colleague(auth_env, merchant, name: str):
    """Another active staff member of the same merchant, who never signs in."""
    user, _merchant = await auth_env.create_merchant_staff(merchant, roles=("manager",))
    await _rename(auth_env, user.id, name)
    user.full_name = name
    return user


async def _rename(auth_env, user_id: str, name: str) -> None:
    """Give a user a distinct name, so activity lines and mentions are readable in a failure."""
    from sqlalchemy import update

    from app.modules.users.models import User

    await auth_env.execute(update(User).where(User.id == user_id).values(full_name=name))


async def team_of(auth_env):
    """A signed-in creator plus two colleagues. Returns (token, merchant, creator, priya, amit)."""
    token, merchant, creator = await task_staff(auth_env, name="Rajesh Verma")
    priya = await colleague(auth_env, merchant, "Priya Nair")
    amit = await colleague(auth_env, merchant, "Amit Verma")
    return token, merchant, creator, priya, amit


def tomorrow() -> str:
    return (business_today() + timedelta(days=1)).isoformat()


def body(**overrides) -> dict:
    """A valid create-task body, with whatever the test wants changed."""
    return {
        "title": "Verify godown stock",
        "description": "Cross-check the physical count against the ledger.",
        "priority": "HIGH",
        "dueDate": tomorrow(),
        **overrides,
    }


async def create_task(auth_env, token: str, **overrides) -> dict:
    response = await auth_env.post(TASKS, token, body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def get_task(auth_env, token: str, task_id: str) -> dict:
    response = await auth_env.get(f"{TASKS}/{task_id}", token)
    assert response.status_code == 200, response.text
    return response.json()


async def messages(auth_env, token: str, task_id: str) -> list[dict]:
    response = await auth_env.get(f"{TASKS}/{task_id}/messages", token)
    assert response.status_code == 200, response.text
    return response.json()


async def activity(auth_env, token: str, task_id: str) -> list[str]:
    """Just the action strings, which is what a test usually asserts on."""
    response = await auth_env.get(f"{TASKS}/{task_id}/activity", token)
    assert response.status_code == 200, response.text
    return [row["action"] for row in response.json()]


async def upload(auth_env, token: str, *, name: str = "stock_count.png") -> dict:
    """Upload a real file through the documents endpoint and return its metadata."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = await auth_env.client.post(
        DOCUMENTS,
        files={"file": (name, png, "image/png")},
        data={"type": "TASK_ATTACHMENT"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()
