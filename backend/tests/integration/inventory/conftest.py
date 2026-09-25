"""Fixtures for the warehouse slice.

Reuses the authentication suite's database, migration and environment fixtures, the way the
order, pricing and expense suites do. That conftest is imported here, never edited.

Staff are created with the inventory permissions on a throwaway role, so a test that is about
stock does not depend on how the deployment happens to have configured `manager`.
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
MERCHANT_AUTH = f"{MERCHANT}/auth"
INVENTORY = f"{MERCHANT}/inventory"
MOVEMENTS = f"{INVENTORY}/movements"

VIEW_ONLY = ("inventory.view",)
FULL = ("inventory.view", "inventory.adjust")


@pytest.fixture
def settings_overrides() -> dict:
    """Required by the shared `env` fixture; the warehouse needs no setting changed."""
    return {}


async def godown_staff(auth_env, merchant=None, permissions: tuple[str, ...] = FULL):
    """Merchant staff holding the inventory permissions. Returns (token, merchant, user)."""
    role = f"godown_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def record(auth_env, token: str, **body):
    """Post one movement. Returns the raw response so failures can be asserted too."""
    payload = {"cylinderType": "LPG_19KG", **body}
    return await auth_env.post(MOVEMENTS, token, payload)


async def recorded(auth_env, token: str, **body) -> dict:
    response = await record(auth_env, token, **body)
    assert response.status_code == 201, response.text
    return response.json()


async def refill(auth_env, token: str, cylinder: str = "LPG_19KG", quantity: int = 60, **body) -> dict:
    """The usual way stock gets into a godown, for tests that need a starting count."""
    return await recorded(
        auth_env,
        token,
        type="RECEIVED_FILLED",
        cylinderType=cylinder,
        quantity=quantity,
        **body,
    )


async def snapshot(auth_env, token: str) -> dict:
    response = await auth_env.get(INVENTORY, token)
    assert response.status_code == 200, response.text
    return response.json()


def card(body: dict, cylinder: str = "LPG_19KG") -> dict:
    """One cylinder's card out of a snapshot."""
    found = [item for item in body["items"] if item["cylinderType"] == cylinder]
    assert found, f"{cylinder} is missing from the snapshot"
    return found[0]


def counts(body: dict, cylinder: str = "LPG_19KG") -> tuple[int, int, int]:
    """`(filled, empty, damaged)` for one cylinder - the three numbers most tests assert on."""
    item = card(body, cylinder)
    return item["filled"], item["empty"], item["damaged"]
