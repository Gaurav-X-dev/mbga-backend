"""Recording, editing and deleting spend, and the validation the Add sheet relies on."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.shared.date_time.business_calendar import business_today, month_key
from tests.integration.expenses.conftest import (
    CATEGORIES,
    EXPENSES,
    add_expense,
    categories,
    category_id,
    code_of,
    created_expense,
    delete,
    expense_staff,
    patch,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_an_expense_is_filed_with_the_session_user_and_derived_period(env):
    token, _merchant, user = await expense_staff(env)
    today = business_today()

    expense = await created_expense(env, token, amount=4200, note="Diesel - MP09 GH 4521")

    assert Decimal(str(expense["amount"])) == Decimal(4200)
    assert expense["note"] == "Diesel - MP09 GH 4521"
    assert expense["date"] == today.isoformat()
    # Both derived server-side, never read from the body.
    assert expense["period"] == month_key(today)
    assert expense["recordedBy"] == user.full_name
    assert expense["category"]["code"] == "FUEL"
    assert expense["category"]["label"] == "Fuel"
    assert expense["category"]["icon"] == "fuel"


async def test_amounts_are_json_numbers_and_timestamps_are_utc(env):
    token, _merchant, _user = await expense_staff(env)

    expense = await created_expense(env, token)

    assert isinstance(expense["amount"], (int, float))
    assert expense["createdAt"].endswith("Z")
    assert expense["updatedAt"].endswith("Z")


async def test_the_period_label_is_ready_for_the_screen(env):
    token, _merchant, _user = await expense_staff(env)

    expense = await created_expense(env, token)

    # The list row reads "23 Sep 2026 - Mohan Lal - September 2026"; the label is built
    # here so every client does not reimplement month names.
    assert expense["periodLabel"] == "September 2026"


async def test_a_category_code_may_be_sent_instead_of_an_id(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)

    response = await add_expense(env, token, category="utilities", amount=6800)

    assert response.status_code == 201, response.text
    assert response.json()["category"]["code"] == "UTILITIES"


async def test_back_dating_moves_the_report_period_with_it(env):
    token, _merchant, _user = await expense_staff(env)
    last_month = business_today().replace(day=1) - timedelta(days=1)

    expense = await created_expense(env, token, date=last_month.isoformat())

    assert expense["date"] == last_month.isoformat()
    assert expense["period"] == month_key(last_month)


async def test_a_note_is_optional_and_blank_becomes_null(env):
    token, _merchant, _user = await expense_staff(env)

    without = await created_expense(env, token, note=None)
    blank = await created_expense(env, token, note="   ")

    assert without["note"] is None
    assert blank["note"] is None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"amount": 0}, "amount"),
        ({"amount": -500}, "amount"),
        ({"amount": None}, "amount"),
        ({"amount": 100000000}, "amount"),
        ({"note": "x" * 256}, "note"),
    ],
)
async def test_invalid_amounts_and_notes_are_rejected_by_field(env, overrides, field):
    token, _merchant, _user = await expense_staff(env)

    response = await add_expense(env, token, **overrides)

    assert response.status_code == 422, response.text
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == field


async def test_a_future_date_is_refused(env):
    """Money that has not been spent yet is not an expense."""
    token, _merchant, _user = await expense_staff(env)
    tomorrow = business_today() + timedelta(days=1)

    response = await add_expense(env, token, date=tomorrow.isoformat())

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["code"] == "date_in_future"


async def test_a_mistyped_year_is_refused(env):
    token, _merchant, _user = await expense_staff(env)

    response = await add_expense(env, token, date="2019-09-23")

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["code"] == "date_too_old"


async def test_a_paise_amount_is_rounded_to_what_is_stored(env):
    token, _merchant, _user = await expense_staff(env)

    expense = await created_expense(env, token, amount=1234.567)

    assert Decimal(str(expense["amount"])) == Decimal("1234.57")


async def test_a_missing_category_is_a_field_error_not_a_crash(env):
    token, _merchant, _user = await expense_staff(env)

    response = await env.post(EXPENSES, token, json={"amount": 100})

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "categoryId"


async def test_an_unknown_category_is_not_found(env):
    token, _merchant, _user = await expense_staff(env)

    response = await add_expense(env, token, categoryId="does-not-exist")

    assert response.status_code == 404
    assert code_of(response) == "EXPENSE_CATEGORY_NOT_FOUND"


async def test_nothing_new_can_be_filed_against_a_deactivated_category(env):
    """Otherwise a category taken out of the picker keeps collecting rows."""
    token, _merchant, _user = await expense_staff(env)
    rent = await category_id(env, token, "RENT")
    await patch(env, f"{CATEGORIES}/{rent}", token, {"isActive": False})

    response = await add_expense(env, token, categoryId=rent)

    assert response.status_code == 409
    assert code_of(response) == "CONFLICT"


async def test_another_merchants_category_cannot_be_used(env):
    theirs, _their_merchant, _their_user = await expense_staff(env)
    their_fuel = await category_id(env, theirs, "FUEL")
    ours, _merchant, _user = await expense_staff(env)

    response = await add_expense(env, ours, categoryId=their_fuel)

    assert response.status_code == 404


# --- Detail, update, delete -----------------------------------------------------------------


async def test_an_expense_can_be_read_back(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token)

    response = await env.get(f"{EXPENSES}/{created['id']}", token)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]


async def test_a_partial_update_leaves_omitted_fields_alone(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token, amount=4200, note="Diesel")

    response = await patch(env, f"{EXPENSES}/{created['id']}", token, {"amount": 4500})

    assert response.status_code == 200, response.text
    updated = response.json()
    assert Decimal(str(updated["amount"])) == Decimal(4500)
    assert updated["note"] == "Diesel"
    assert updated["date"] == created["date"]


async def test_an_empty_note_clears_it(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token, note="Diesel")

    response = await patch(env, f"{EXPENSES}/{created['id']}", token, {"note": ""})

    assert response.json()["note"] is None


async def test_moving_the_date_moves_the_period_too(env):
    """The two can never drift apart, because the period is recomputed, not edited."""
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token)
    last_month = business_today().replace(day=1) - timedelta(days=1)

    response = await patch(env, f"{EXPENSES}/{created['id']}", token, {"date": last_month.isoformat()})

    assert response.json()["period"] == month_key(last_month)
    assert response.json()["period"] != created["period"]


async def test_the_category_can_be_changed(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token)
    salary = await category_id(env, token, "SALARY")

    response = await patch(env, f"{EXPENSES}/{created['id']}", token, {"categoryId": salary})

    assert response.json()["category"]["code"] == "SALARY"


async def test_an_update_is_validated_like_a_create(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token)

    response = await patch(env, f"{EXPENSES}/{created['id']}", token, {"amount": -1})

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "amount"


async def test_an_expense_can_be_deleted(env):
    token, _merchant, _user = await expense_staff(env)
    created = await created_expense(env, token)

    removed = await delete(env, f"{EXPENSES}/{created['id']}", token)

    assert removed.status_code == 204
    assert (await env.get(f"{EXPENSES}/{created['id']}", token)).status_code == 404


async def test_another_merchants_expense_is_not_found_rather_than_forbidden(env):
    theirs, _their_merchant, _their_user = await expense_staff(env)
    their_expense = await created_expense(env, theirs)
    ours, _merchant, _user = await expense_staff(env)

    read = await env.get(f"{EXPENSES}/{their_expense['id']}", ours)
    edit = await patch(env, f"{EXPENSES}/{their_expense['id']}", ours, {"amount": 1})
    removed = await delete(env, f"{EXPENSES}/{their_expense['id']}", ours)

    assert read.status_code == 404
    assert edit.status_code == 404
    assert removed.status_code == 404
    assert code_of(read) == "EXPENSE_NOT_FOUND"


async def test_writing_needs_expenses_manage(env):
    token, _merchant, _user = await expense_staff(env, permissions=("expenses.view",))
    await categories(env, token)

    blocked = await add_expense(env, token)

    assert blocked.status_code == 403


async def test_reading_needs_expenses_view(env):
    token, _merchant, _user = await expense_staff(env, permissions=("customers.view",))

    response = await env.get(EXPENSES, token)

    assert response.status_code == 403
