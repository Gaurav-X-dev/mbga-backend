"""The Tasks list, its four tabs and its filters - and who may see any of it.

The list is the module's home screen, so its scopes are behaviour rather than convenience: "My
Tasks" that quietly includes tasks you merely created is a tab nobody can trust.

The access tests are the negative ones. A task carries what a merchant's staff say to each other
about their own customers and stock; one merchant's board appearing in another's is a breach.
"""

import pytest

from tests.integration.tasks.conftest import (
    TASKS,
    TEAM,
    code_of,
    colleague,
    create_task,
    task_staff,
    team_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def listed(env, token: str, **params) -> dict:
    response = await env.get(TASKS, token, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


async def titles(env, token: str, **params) -> list[str]:
    return [row["title"] for row in (await listed(env, token, **params))["items"]]


async def patch(env, token: str, task_id: str, **payload):
    return await env.client.patch(
        f"{TASKS}/{task_id}/status", json=payload, headers={"Authorization": f"Bearer {token}"}
    )


# --- The four tabs -------------------------------------------------------------------------------


async def test_all_is_the_default_scope(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    await create_task(env, token, title="One", assignedUserIds=[priya.id])
    await create_task(env, token, title="Two", assignedUserIds=[priya.id])

    assert sorted(await titles(env, token)) == ["One", "Two"]


async def test_my_tasks_means_assigned_to_me(env):
    """Not "created by me" - that is the other tab, and conflating them makes both useless."""
    token, merchant, creator, priya, _amit = await team_of(env)
    await create_task(env, token, title="Mine", assignedUserIds=[creator.id])
    await create_task(env, token, title="Theirs", assignedUserIds=[priya.id])

    assert await titles(env, token, scope="MY") == ["Mine"]
    assert merchant


async def test_assigned_means_created_by_me(env):
    """The screen calls this "Assigned by Me"."""
    token, merchant, _creator, priya, _amit = await team_of(env)
    await create_task(env, token, title="I raised this", assignedUserIds=[priya.id])
    colleague_token, _same, _user = await task_staff(env, merchant, name="Someone Else")
    await create_task(env, colleague_token, title="They raised this", assignedUserIds=[priya.id])

    assert await titles(env, token, scope="ASSIGNED") == ["I raised this"]


async def test_completed_ignores_who_created_or_was_assigned(env):
    """The tab is "what is done here", not "what I finished"."""
    token, merchant, _creator, priya, _amit = await team_of(env)
    other_token, _same, _user = await task_staff(env, merchant, name="Someone Else")
    theirs = await create_task(env, other_token, title="Theirs, done", assignedUserIds=[priya.id])
    await create_task(env, token, title="Mine, open", assignedUserIds=[priya.id])
    await patch(env, other_token, theirs["id"], status="COMPLETED")

    assert await titles(env, token, scope="COMPLETED") == ["Theirs, done"]


# --- Filters ----------------------------------------------------------------------------------------


async def test_status_and_priority_filters_are_or_ed(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    low = await create_task(env, token, title="Low", priority="LOW", assignedUserIds=[priya.id])
    await create_task(env, token, title="High", priority="HIGH", assignedUserIds=[priya.id])
    await create_task(env, token, title="Critical", priority="CRITICAL", assignedUserIds=[priya.id])
    await patch(env, token, low["id"], status="ON_HOLD")

    by_priority = await listed(env, token, priority=["LOW", "CRITICAL"])
    by_status = await listed(env, token, status=["ON_HOLD"])

    assert sorted(row["title"] for row in by_priority["items"]) == ["Critical", "Low"]
    assert [row["title"] for row in by_status["items"]] == ["Low"]


async def test_overdue_never_includes_a_completed_task(env):
    """However late it was finished, a done task is not something to chase."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.modules.tasks.models import Task
    from app.shared.date_time.business_calendar import business_today

    token, _merchant, _creator, priya, _amit = await team_of(env)
    late = await create_task(env, token, title="Late", assignedUserIds=[priya.id])
    done = await create_task(env, token, title="Late but done", assignedUserIds=[priya.id])
    # Backdate both past the due date, which the create endpoint rightly refuses to do.
    yesterday = business_today() - timedelta(days=3)
    await env.execute(
        update(Task).where(Task.id.in_([late["id"], done["id"]])).values(due_date=yesterday)
    )
    await patch(env, token, done["id"], status="COMPLETED")

    assert await titles(env, token, due="OVERDUE") == ["Late"]


async def test_the_due_filters_pick_the_right_days(env):
    """TODAY and TOMORROW are exact days; THIS_WEEK runs from today through Sunday.

    Due dates are set directly rather than through the endpoint, which rightly refuses anything in
    the past - and a test that only ever looks forward cannot check a boundary.
    """
    from datetime import timedelta

    from sqlalchemy import update

    from app.modules.tasks.models import Task
    from app.shared.date_time.business_calendar import business_today

    token, _merchant, _creator, priya, _amit = await team_of(env)
    today = business_today()
    # Monday is 0, so this is the coming Sunday - the last day THIS_WEEK covers.
    sunday = today + timedelta(days=6 - today.weekday())
    for label, due in (
        ("Today", today),
        ("Tomorrow", today + timedelta(days=1)),
        ("End of week", sunday),
        ("Next week", sunday + timedelta(days=1)),
    ):
        task = await create_task(env, token, title=label, assignedUserIds=[priya.id])
        await env.execute(update(Task).where(Task.id == task["id"]).values(due_date=due))

    # Exact-day matches, so these hold whatever weekday the suite runs on.
    assert await titles(env, token, due="TODAY") == ["Today"]
    assert await titles(env, token, due="TOMORROW") == ["Tomorrow"]
    this_week = set(await titles(env, token, due="THIS_WEEK"))
    assert "Today" in this_week
    assert "End of week" in this_week
    assert "Next week" not in this_week, "the window stops at Sunday"


async def test_an_unknown_due_chip_shows_nothing_rather_than_an_error(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    await create_task(env, token, assignedUserIds=[priya.id])

    assert await titles(env, token, due="SOMEDAY") == []


async def test_search_matches_the_things_staff_actually_type(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(
        env, token, title="Verify godown stock", description="Count the 19 KG rack", assignedUserIds=[priya.id]
    )
    await create_task(env, token, title="Call the plant", assignedUserIds=[priya.id])

    assert await titles(env, token, search="godown") == ["Verify godown stock"]
    assert await titles(env, token, search="19 KG") == ["Verify godown stock"]
    assert await titles(env, token, search=task["id"]) == ["Verify godown stock"]
    assert sorted(await titles(env, token, search="Priya")) == ["Call the plant", "Verify godown stock"]


async def test_a_search_that_matches_nothing_is_empty(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    await create_task(env, token, assignedUserIds=[priya.id])

    assert await titles(env, token, search="nothing like this") == []


# --- Ordering and paging -------------------------------------------------------------------------------


async def test_the_list_is_newest_activity_first(env):
    """Fixed sort: it is a work queue, and what changed last is what the team needs to see."""
    token, _merchant, _creator, priya, _amit = await team_of(env)
    first = await create_task(env, token, title="First", assignedUserIds=[priya.id])
    await create_task(env, token, title="Second", assignedUserIds=[priya.id])
    await create_task(env, token, title="Third", assignedUserIds=[priya.id])

    before = await titles(env, token)
    await patch(env, token, first["id"], status="IN_PROGRESS")
    after = await titles(env, token)

    assert before == ["Third", "Second", "First"]
    assert after[0] == "First", "touching a task brings it to the top"


async def test_paging_reports_the_whole_count(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    for index in range(5):
        await create_task(env, token, title=f"Task {index}", assignedUserIds=[priya.id])

    page = await listed(env, token, page=2, pageSize=2)

    assert page["total"] == 5
    assert page["page"] == 2
    assert page["pageSize"] == 2
    assert len(page["items"]) == 2


async def test_a_page_past_the_end_is_empty_not_an_error(env):
    token, _merchant, _creator, priya, _amit = await team_of(env)
    await create_task(env, token, assignedUserIds=[priya.id])

    page = await listed(env, token, page=9)

    assert page["items"] == []
    assert page["total"] == 1


# --- The team directory ---------------------------------------------------------------------------------


async def test_the_team_lists_this_merchants_active_staff(env):
    token, _merchant, _creator, _priya, _amit = await team_of(env)

    members = await env.get(TEAM, token)

    assert members.status_code == 200
    names = [row["name"] for row in members.json()]
    assert set(names) >= {"Rajesh Verma", "Priya Nair", "Amit Verma"}


async def test_the_team_carries_a_role_and_a_branch(env):
    """The app derives the display title from `role` and the avatar colour from `id` itself."""
    token, merchant, _creator, _priya, _amit = await team_of(env)

    member = (await env.get(TEAM, token)).json()[0]

    assert member["role"]
    assert member["branchName"] == merchant.name
    assert set(member) == {"id", "name", "role", "branchName"}


async def test_the_team_can_be_searched(env):
    token, _merchant, _creator, _priya, _amit = await team_of(env)

    found = (await env.get(TEAM, token, params={"search": "Priya"})).json()

    assert [row["name"] for row in found] == ["Priya Nair"]


async def test_another_merchants_staff_are_not_on_the_team(env):
    token, _merchant, _creator, _priya, _amit = await team_of(env)
    _other_token, other_merchant, _other = await task_staff(env)
    await colleague(env, other_merchant, "Outsider")

    names = [row["name"] for row in (await env.get(TEAM, token)).json()]

    assert "Outsider" not in names


# --- Tenancy and permissions ---------------------------------------------------------------------------------


async def test_one_merchants_tasks_are_invisible_to_another(env):
    mine_token, _mine, _c1, priya, _a1 = await team_of(env)
    theirs_token, theirs_merchant, _c2, _p2, _a2 = await team_of(env)
    outsider = await colleague(env, theirs_merchant, "Their Person")
    await create_task(env, theirs_token, title="Their task", assignedUserIds=[outsider.id])
    await create_task(env, mine_token, title="My task", assignedUserIds=[priya.id])

    assert await titles(env, mine_token) == ["My task"]


async def test_another_merchants_task_is_a_404(env):
    """`TASK-000123` is guessable by design, so a 403 would confirm it exists."""
    theirs_token, theirs_merchant, _c, _p, _a = await team_of(env)
    outsider = await colleague(env, theirs_merchant, "Their Person")
    theirs = await create_task(env, theirs_token, assignedUserIds=[outsider.id])
    mine_token, _mine, _c2, _p2, _a2 = await team_of(env)

    for path in ("", "/messages", "/activity"):
        response = await env.get(f"{TASKS}/{theirs['id']}{path}", mine_token)
        assert response.status_code == 404, path
        assert code_of(response) == "TASK_NOT_FOUND"


async def test_another_merchants_task_cannot_be_updated(env):
    theirs_token, theirs_merchant, _c, _p, _a = await team_of(env)
    outsider = await colleague(env, theirs_merchant, "Their Person")
    theirs = await create_task(env, theirs_token, assignedUserIds=[outsider.id])
    mine_token, _mine, _c2, _p2, _a2 = await team_of(env)

    updated = await patch(env, mine_token, theirs["id"], status="COMPLETED")
    posted = await env.post(f"{TASKS}/{theirs['id']}/messages", mine_token, {"text": "hello"})

    assert updated.status_code == 404
    assert posted.status_code == 404


async def test_any_colleague_may_update_anyone_elses_task(env):
    """The spec's explicit decision: one flat permission, no owner rule.

    The screens do not expect a 403 on somebody else's task, so adding one here would break them
    quietly rather than protect anything.
    """
    token, merchant, _creator, priya, _amit = await team_of(env)
    task = await create_task(env, token, assignedUserIds=[priya.id])
    colleague_token, _same, _user = await task_staff(env, merchant, name="Someone Else")

    updated = await patch(env, colleague_token, task["id"], status="IN_PROGRESS")
    posted = await env.post(f"{TASKS}/{task['id']}/messages", colleague_token, {"text": "on it"})

    assert updated.status_code == 200
    assert posted.status_code == 201


async def test_everything_needs_the_tasks_permission(env):
    token, _merchant, _user = await task_staff(env, permissions=("orders.view",))

    for path in (TASKS, TEAM):
        response = await env.get(path, token)
        assert response.status_code == 403, path
        assert code_of(response) == "PERMISSION_DENIED"


async def test_everything_needs_a_session(env):
    assert (await env.get(TASKS)).status_code == 401
    assert (await env.get(TEAM)).status_code == 401


async def test_a_customer_token_cannot_reach_tasks(env):
    """Tasks are staff talking to each other about work; there is no customer-facing view."""
    from tests.integration.notifications.conftest import customer as signed_in_customer
    from tests.integration.notifications.conftest import staff

    _staff_token, merchant, _u = await staff(env)
    customer_token, _profile, _cu = await signed_in_customer(env, merchant)

    mismatch = await env.get(TASKS, customer_token)
    missing = await env.get("/api/v1/customer/tasks", customer_token)

    assert mismatch.status_code == 403
    assert code_of(mismatch) == "CHANNEL_NOT_ALLOWED"
    assert missing.status_code == 404
