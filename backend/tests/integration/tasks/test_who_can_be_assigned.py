"""Who the Assign To picker offers, and who it must not.

Tasks are an internal board: the office giving work to its own people. The picker read
`merchant_users` alone, and two things followed from that.

**Drivers and helpers do not belong here.** The delivery app has no task screen, so a task
given to a driver would sit unread; their work reaches them as delivery slips. They have no
`merchant_users` row either, so the office picker must not pick them up by any other route.

**A customer appeared.** One mobile can be registered as a customer and later added as staff, and such
a person does belong here - as staff. But the role shown came from `min(role.code)`, and
`customer` sorts before every staff role, so they were listed with "Customer" written under
their name on an internal board.
"""

import pytest
from sqlalchemy import update

from app.modules.users.models import User
from tests.integration.tasks.conftest import (  # noqa: F401 - fixtures
    MERCHANT,
    TASKS,
    TEAM,
    body,
    colleague,
    env,
    task_staff,
    team_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def picker(env, token) -> dict[str, dict]:
    response = await env.get(TEAM, token)
    assert response.status_code == 200, response.text
    return {row["name"]: row for row in response.json()}


async def a_driver(env, merchant, name: str, *, status: str = "ACTIVE", approval: str = "APPROVED"):
    """A real driver of this merchant: a `delivery_profiles` row and no `merchant_users` one."""
    user, _merchant, _profile = await env.create_delivery_user(
        merchant, status=status, approval_status=approval
    )
    await env.execute(update(User).where(User.id == user.id).values(full_name=name))
    user.full_name = name
    return user


# --- The driver who was missing --------------------------------------------------------------


async def test_the_picker_lists_this_merchants_staff(env):
    token, _merchant, _creator, priya, amit = await team_of(env)

    names = await picker(env, token)

    assert "Priya Nair" in names
    assert "Amit Verma" in names


async def test_a_driver_is_not_offered(env):
    """Tasks are an office board. A driver's work reaches them as delivery slips."""
    token, merchant, _creator, _priya, _amit = await team_of(env)
    driver = await a_driver(env, merchant, "Suresh Yadav")

    listed = {row["id"] for row in (await env.get(TEAM, token)).json()}

    assert driver.id not in listed


async def test_a_task_may_not_be_given_to_a_driver(env):
    """Offered or not, the write has to refuse: the picker is not the only way to call it."""
    token, merchant, _creator, _priya, _amit = await team_of(env)
    driver = await a_driver(env, merchant, "Suresh Yadav")

    created = await env.post(TASKS, token, body(assignedUserIds=[driver.id]))

    assert created.status_code == 422, created.text


async def test_a_customer_is_not_offered(env):
    """The case from production: "Aryan Nara · Customer" on an internal board."""
    token, merchant, _creator, _priya, _amit = await team_of(env)
    buyer, _m = await env.create_merchant_staff(merchant, roles=("customer",))
    assert buyer

    roles = {row["role"] for row in (await picker(env, token)).values()}

    assert "CUSTOMER" not in roles


async def test_the_job_title_the_office_chose_is_what_is_shown(env):
    """Every merchant user is assigned the `manager` role whatever their job, so reading the
    role alone called an accountant a manager."""
    token, merchant, _creator, _priya, _amit = await team_of(env)
    clerk, _m = await env.create_merchant_staff(merchant, roles=("manager",), staff_type="ACCOUNTANT")

    listed = {row["id"]: row for row in (await env.get(TEAM, token)).json()}

    assert listed[clerk.id]["role"] == "ACCOUNTANT"


async def test_somebody_who_is_both_reads_as_their_staff_role(env):
    """A manager who also buys gas from their own agency is staff here, not a customer."""
    token, merchant, _creator, _priya, _amit = await team_of(env)
    both, _m = await env.create_merchant_staff(merchant, roles=("manager", "customer"))

    listed = {row["id"]: row for row in (await env.get(TEAM, token)).json()}

    assert listed[both.id]["role"] != "CUSTOMER"


# --- What may be assigned --------------------------------------------------------------------


async def test_a_task_may_be_given_to_a_colleague(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)

    created = await env.post(TASKS, token, body(assignedUserIds=[priya.id]))

    assert created.status_code == 201, created.text


async def test_a_task_may_not_be_given_to_somebody_outside_the_merchant(env):
    token, _merchant, _creator, _priya, _amit = await team_of(env)
    _other_token, other_merchant, outsider = await task_staff(env, name="Someone Else")
    assert other_merchant

    created = await env.post(TASKS, token, body(assignedUserIds=[outsider.id]))

    assert created.status_code == 422, created.text


async def test_the_picker_and_the_assignment_agree(env):
    """One membership rule behind both, or the picker offers somebody the write refuses."""
    token, _merchant, _creator, _priya, _amit = await team_of(env)

    offered = (await env.get(TEAM, token)).json()

    for row in offered:
        created = await env.post(TASKS, token, body(assignedUserIds=[row["id"]]))
        assert created.status_code == 201, f"{row['name']} was offered but refused: {created.text}"
