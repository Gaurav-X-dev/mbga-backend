"""The dynamic category list behind the Category sheet."""

import pytest

from tests.integration.expenses.conftest import (
    CATEGORIES,
    DEFAULT_CODES,
    categories,
    category_id,
    code_of,
    created_expense,
    delete,
    expense_staff,
    patch,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_first_call_seeds_the_starting_set_in_picker_order(env):
    """The Add sheet expects a filled picker the first time it opens."""
    token, _merchant, _user = await expense_staff(env)

    items = await categories(env, token)

    assert [item["code"] for item in items] == DEFAULT_CODES
    assert [item["label"] for item in items][:2] == ["Fuel", "Vehicle Maintenance"]
    assert all(item["isActive"] for item in items)
    assert all(item["isCustom"] is False for item in items)
    assert all(item["expenseCount"] == 0 for item in items)


async def test_every_seeded_icon_is_one_the_app_can_draw(env):
    token, _merchant, _user = await expense_staff(env)

    items = await categories(env, token)

    assert {item["icon"] for item in items} <= {
        "fuel",
        "maintenance",
        "salary",
        "rent",
        "utilities",
        "misc",
    }


async def test_seeding_runs_once_not_on_every_read(env):
    token, _merchant, _user = await expense_staff(env)

    first = await categories(env, token)
    second = await categories(env, token)

    assert len(first) == len(DEFAULT_CODES)
    assert [item["id"] for item in first] == [item["id"] for item in second]


async def test_each_merchant_gets_their_own_copy(env):
    ours, _merchant, _user = await expense_staff(env)
    theirs, _other, _other_user = await expense_staff(env)

    our_ids = {item["id"] for item in await categories(env, ours)}
    their_ids = {item["id"] for item in await categories(env, theirs)}

    assert our_ids.isdisjoint(their_ids)


async def test_a_merchant_can_add_their_own_category(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)

    response = await env.post(CATEGORIES, token, json={"label": "Godown Repairs", "icon": "maintenance"})

    assert response.status_code == 201, response.text
    created = response.json()
    # The code is generated from the name, which is all the app's form collects.
    assert created["code"] == "GODOWN_REPAIRS"
    assert created["label"] == "Godown Repairs"
    assert created["isCustom"] is True
    assert created["code"] in [item["code"] for item in await categories(env, token)]


async def test_a_duplicate_code_is_a_conflict_not_a_second_row(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)

    response = await env.post(CATEGORIES, token, json={"label": "Fuel"})

    assert response.status_code == 409
    assert code_of(response) == "CONFLICT"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"label": "  "}, "label"),
        ({"label": "Tolls", "code": "not lower"}, "code"),
        ({"label": "Tolls", "code": "9BAD"}, "code"),
        ({"label": "Tolls", "icon": "rocket"}, "icon"),
        ({"label": "x" * 61}, "label"),
    ],
)
async def test_invalid_category_input_is_rejected(env, body, field):
    token, _merchant, _user = await expense_staff(env)

    response = await env.post(CATEGORIES, token, json=body)

    assert response.status_code == 422, response.text
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == field


async def test_a_name_starting_with_a_digit_still_gets_a_valid_code(env):
    token, _merchant, _user = await expense_staff(env)

    response = await env.post(CATEGORIES, token, json={"label": "24x7 Security"})

    assert response.status_code == 201, response.text
    # A code must start with a letter, so the generator prefixes rather than rejecting a
    # name the operator was entitled to type.
    assert response.json()["code"] == "C_24X7_SECURITY"


async def test_renaming_keeps_the_code_so_history_and_filters_survive(env):
    token, _merchant, _user = await expense_staff(env)
    fuel = await category_id(env, token, "FUEL")

    response = await patch(env, f"{CATEGORIES}/{fuel}", token, {"label": "Diesel & Petrol"})

    assert response.status_code == 200, response.text
    assert response.json()["label"] == "Diesel & Petrol"
    assert response.json()["code"] == "FUEL"


async def test_a_deactivated_category_leaves_the_picker(env):
    token, _merchant, _user = await expense_staff(env)
    rent = await category_id(env, token, "RENT")

    await patch(env, f"{CATEGORIES}/{rent}", token, {"isActive": False})

    assert "RENT" not in [item["code"] for item in await categories(env, token)]
    # A management screen can still see it.
    everything = (await env.get(f"{CATEGORIES}?includeInactive=true", token)).json()
    assert "RENT" in [item["code"] for item in everything]


async def test_an_unused_category_is_deleted_outright(env):
    token, _merchant, _user = await expense_staff(env)
    created = (await env.post(CATEGORIES, token, json={"label": "Tolls"})).json()

    response = await delete(env, f"{CATEGORIES}/{created['id']}", token)

    assert response.status_code == 200, response.text
    everything = (await env.get(f"{CATEGORIES}?includeInactive=true", token)).json()
    assert created["id"] not in [item["id"] for item in everything]


async def test_a_category_in_use_is_deactivated_not_deleted(env):
    """Deleting it would leave filed expenses without the label they were reported under."""
    token, _merchant, _user = await expense_staff(env)
    fuel = await category_id(env, token, "FUEL")
    await created_expense(env, token, categoryId=fuel)

    response = await delete(env, f"{CATEGORIES}/{fuel}", token)

    assert response.status_code == 200, response.text
    assert response.json()["isActive"] is False
    everything = (await env.get(f"{CATEGORIES}?includeInactive=true", token)).json()
    assert fuel in [item["id"] for item in everything]


async def test_expense_count_tells_the_app_what_is_in_use(env):
    token, _merchant, _user = await expense_staff(env)
    fuel = await category_id(env, token, "FUEL")
    await created_expense(env, token, categoryId=fuel)
    await created_expense(env, token, categoryId=fuel)

    items = await categories(env, token)

    assert next(item for item in items if item["id"] == fuel)["expenseCount"] == 2
    assert next(item for item in items if item["code"] == "RENT")["expenseCount"] == 0


async def test_another_merchants_category_is_not_found(env):
    theirs, _their_merchant, _their_user = await expense_staff(env)
    their_fuel = await category_id(env, theirs, "FUEL")
    ours, _merchant, _user = await expense_staff(env)

    response = await patch(env, f"{CATEGORIES}/{their_fuel}", ours, {"label": "Hijacked"})

    assert response.status_code == 404
    assert code_of(response) == "EXPENSE_CATEGORY_NOT_FOUND"


async def test_managing_categories_needs_expenses_manage(env):
    token, _merchant, _user = await expense_staff(env, permissions=("expenses.view",))

    readable = await env.get(CATEGORIES, token)
    blocked = await env.post(CATEGORIES, token, json={"label": "Tolls"})

    assert readable.status_code == 200
    assert blocked.status_code == 403


async def test_categories_need_a_session(env):
    response = await env.get(CATEGORIES)

    assert response.status_code == 401
