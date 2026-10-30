"""Leaving blocked and inactive agencies out of the merchant list.

The admin panel picks a merchant in several places - assigning staff, filtering a report - and
a blocked agency has no business being offered there: nothing can be assigned to it and no
order can reach it.

Doing that in the browser does not work. The response carries `total` alongside one page, so a
list the panel filtered itself would show eighty rows under a total of two hundred and fifty,
and page two would skip whatever page one dropped. The filter has to be where the count is.

`excludeStatus` is opt-in. The merchants screen itself still lists blocked agencies, because
the unblock button lives on those rows.
"""

import pytest
from sqlalchemy import update

from app.modules.merchants.models import Merchant
from tests.integration.deliveries.conftest import dispatch_staff

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
MERCHANTS = "/api/v1/admin/merchants"


async def admin_token(env) -> str:
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def a_merchant(env, status: str = "ACTIVE"):
    _token, merchant, _user = await dispatch_staff(env)
    if status != "ACTIVE":
        async with env.sessions() as db:
            await db.execute(
                update(Merchant).where(Merchant.id == merchant.id).values(status=status)
            )
            await db.commit()
    return merchant


async def listed(env, token: str, query: str = "") -> dict:
    response = await env.get(f"{MERCHANTS}?limit=100&offset=0{query}", token)
    assert response.status_code == 200, response.text
    return response.json()


def ids(body: dict) -> set[str]:
    return {row["id"] for row in body["items"]}


# --- What the filter leaves out ---------------------------------------------------------------


async def test_a_blocked_agency_is_left_out(env):
    token = await admin_token(env)
    live = await a_merchant(env)
    blocked = await a_merchant(env, "BLOCKED")

    body = await listed(env, token, "&excludeStatus=BLOCKED,INACTIVE")

    assert live.id in ids(body)
    assert blocked.id not in ids(body)


async def test_an_inactive_agency_is_left_out(env):
    token = await admin_token(env)
    inactive = await a_merchant(env, "INACTIVE")

    body = await listed(env, token, "&excludeStatus=BLOCKED,INACTIVE")

    assert inactive.id not in ids(body)


async def test_the_total_drops_with_the_rows(env):
    """The whole reason this is not done in the browser."""
    token = await admin_token(env)
    await a_merchant(env)
    await a_merchant(env, "BLOCKED")

    everything = await listed(env, token)
    filtered = await listed(env, token, "&excludeStatus=BLOCKED,INACTIVE")

    assert filtered["total"] == everything["total"] - 1
    assert len(filtered["items"]) == filtered["total"]


# --- What it leaves alone ----------------------------------------------------------------------


async def test_without_the_filter_blocked_agencies_still_show(env):
    """The merchants screen needs them: the unblock button is on those rows."""
    token = await admin_token(env)
    blocked = await a_merchant(env, "BLOCKED")

    body = await listed(env, token)

    assert blocked.id in ids(body)


async def test_the_exact_status_filter_is_unchanged(env):
    token = await admin_token(env)
    blocked = await a_merchant(env, "BLOCKED")
    live = await a_merchant(env)

    body = await listed(env, token, "&status=BLOCKED")

    assert blocked.id in ids(body)
    assert live.id not in ids(body)


async def test_spacing_and_case_do_not_matter(env):
    """It arrives from a query string, typed by whoever wrote the screen."""
    token = await admin_token(env)
    blocked = await a_merchant(env, "BLOCKED")

    body = await listed(env, token, "&excludeStatus=%20blocked%20,%20inactive%20")

    assert blocked.id not in ids(body)


async def test_an_empty_value_filters_nothing(env):
    """Rather than excluding a status named "", which would hide nothing and look broken."""
    token = await admin_token(env)
    blocked = await a_merchant(env, "BLOCKED")

    body = await listed(env, token, "&excludeStatus=")

    assert blocked.id in ids(body)
