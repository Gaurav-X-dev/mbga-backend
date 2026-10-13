"""Creating a merchant's staff member from the admin panel.

There were two ways to create one and only one of them worked.

`POST /admin/merchants/{id}/users` gave the person a role **and** a `merchant_users` row.
`POST /admin/users` gave them the role alone - and a role is not membership. The team list,
the task picker and every merchant-scoped screen read the link, not the role, so a salesperson
created the second way had the right role, appeared on none of those screens, and nothing
anywhere said why. It was found by querying production after somebody asked where their
salesperson had gone.

`merchantId` on the create call now does both halves.
"""

import pytest
from sqlalchemy import select

from app.modules.merchants.models import MerchantUser
from tests.integration.deliveries.conftest import dispatch_staff

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
USERS = "/api/v1/admin/users"
TEAM = "/api/v1/admin/team"


async def admin_token(env) -> str:
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def a_merchant(env):
    _token, merchant, _user = await dispatch_staff(env)
    return merchant


async def create(env, token, **body):
    return await env.post(USERS, token, body)


async def link_of(env, user_id: str) -> MerchantUser | None:
    async with env.sessions() as db:
        return await db.scalar(
            select(MerchantUser).where(MerchantUser.user_id == user_id)
        )


# --- Naming a merchant joins them to it ----------------------------------------------------------


async def test_a_staff_member_is_linked_to_the_agency(env):
    token = await admin_token(env)
    merchant = await a_merchant(env)

    created = await create(
        env,
        token,
        full_name="Anand Staff",
        mobile_number="9876543214",
        role="salesperson",
        merchantId=merchant.id,
        staffType="SALESPERSON",
    )

    assert created.status_code == 200, created.text
    link = await link_of(env, created.json()["id"])
    assert link is not None, "the role was given but the agency link was not"
    assert link.merchant_id == merchant.id
    assert link.status == "ACTIVE"


async def test_they_appear_on_the_team_list(env):
    """The screen the whole problem was reported from."""
    token = await admin_token(env)
    merchant = await a_merchant(env)
    created = await create(
        env,
        token,
        full_name="Anand Staff",
        mobile_number="9876543215",
        role="salesperson",
        merchantId=merchant.id,
        staffType="SALESPERSON",
    )

    listed = await env.get(f"{TEAM}?merchantId={merchant.id}", token)

    assert listed.status_code == 200, listed.text
    assert created.json()["id"] in {row["id"] for row in listed.json()}


async def test_the_job_title_is_what_was_asked_for(env):
    token = await admin_token(env)
    merchant = await a_merchant(env)
    created = await create(
        env,
        token,
        full_name="Anand Staff",
        mobile_number="9876543216",
        role="salesperson",
        merchantId=merchant.id,
        staffType="SALESPERSON",
    )

    listed = {r["id"]: r for r in (await env.get(f"{TEAM}?merchantId={merchant.id}", token)).json()}

    assert listed[created.json()["id"]]["role"] == "SALESPERSON"


async def test_the_role_stands_in_when_no_title_is_given(env):
    """So a caller who names a merchant and nothing else still reads sensibly."""
    token = await admin_token(env)
    merchant = await a_merchant(env)

    created = await create(
        env,
        token,
        full_name="Anand Staff",
        mobile_number="9876543217",
        role="accountant",
        merchantId=merchant.id,
    )

    link = await link_of(env, created.json()["id"])
    assert link.staff_type == "ACCOUNTANT"


# --- Leaving it out still makes a platform user ----------------------------------------------------


async def test_a_platform_user_belongs_to_no_agency(env):
    """A super admin is not anybody's staff, and must not become so by accident."""
    token = await admin_token(env)

    created = await create(
        env, token, full_name="Platform Admin", mobile_number="9876543218", role="super_admin"
    )

    assert created.status_code == 200, created.text
    assert await link_of(env, created.json()["id"]) is None


async def test_an_unknown_merchant_is_refused(env):
    """Rather than creating a user linked to nothing, which is the state this fixes."""
    token = await admin_token(env)

    created = await create(
        env,
        token,
        full_name="Anand Staff",
        mobile_number="9876543219",
        role="salesperson",
        merchantId="00000000-0000-0000-0000-000000000000",
    )

    assert created.status_code == 404, created.text


async def test_nothing_is_written_when_the_merchant_is_unknown(env):
    """The refusal has to take the user with it, or the half-made account is back."""
    token = await admin_token(env)

    await create(
        env,
        token,
        full_name="Ghost Staff",
        mobile_number="9876543220",
        role="salesperson",
        merchantId="00000000-0000-0000-0000-000000000000",
    )

    listed = await env.get(f"{USERS}?search=Ghost", token)
    assert listed.status_code == 200, listed.text
    assert not [r for r in listed.json()["items"] if r.get("fullName") == "Ghost Staff"]
