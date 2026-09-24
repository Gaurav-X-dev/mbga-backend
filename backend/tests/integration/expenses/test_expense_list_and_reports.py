"""The Expenses list: filter row, summary card, period chips and the category breakdown."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.shared.date_time.business_calendar import business_today, month_key
from tests.integration.expenses.conftest import (
    EXPENSES,
    categories,
    category_id,
    code_of,
    created_expense,
    expense_staff,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def _last_month():
    return business_today().replace(day=1) - timedelta(days=1)


async def _seed_month(env, token):
    """The September card from the screen: five rows across four categories."""
    await categories(env, token)
    rows = [
        ("FUEL", 4200, "Diesel - MP09 GH 4521"),
        ("MISCELLANEOUS", 1150, "Printing of delivery slips"),
        ("VEHICLE_MAINTENANCE", 12500, "Brake service - MP09 HT 7730"),
        ("UTILITIES", 6800, "Electricity bill - godown"),
        ("FUEL", 3900, "Diesel - MP09 KL 1187"),
    ]
    for code, amount, note in rows:
        await created_expense(env, token, category=code, amount=amount, note=note)
    return rows


async def test_the_summary_card_totals_the_whole_period_not_the_page(env):
    """The header reads "Total - September 2026  Rs 28,550   5 entries" above a short page."""
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)

    response = await env.get(f"{EXPENSES}?period={month_key(business_today())}&pageSize=2", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert body["summary"]["entryCount"] == 5
    assert Decimal(str(body["summary"]["totalAmount"])) == Decimal(28550)
    assert body["summary"]["periodLabel"] == "September 2026"


async def test_the_list_is_newest_spend_first(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)
    today = business_today()
    await created_expense(env, token, category="FUEL", date=(today - timedelta(days=7)).isoformat())
    await created_expense(env, token, category="SALARY", date=today.isoformat())

    items = (await env.get(EXPENSES, token)).json()["items"]

    assert items[0]["category"]["code"] == "SALARY"
    assert items[0]["date"] >= items[1]["date"]


async def test_the_category_chip_filters_by_code_or_id(env):
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)
    fuel = await category_id(env, token, "FUEL")

    by_code = (await env.get(f"{EXPENSES}?category=FUEL", token)).json()
    by_id = (await env.get(f"{EXPENSES}?categoryId={fuel}", token)).json()

    assert by_code["summary"]["entryCount"] == 2
    assert Decimal(str(by_code["summary"]["totalAmount"])) == Decimal(8100)
    assert by_id["summary"]["entryCount"] == 2
    assert all(item["category"]["code"] == "FUEL" for item in by_code["items"])


async def test_all_periods_returns_every_month(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)
    await created_expense(env, token, category="FUEL", amount=1000)
    await created_expense(env, token, category="RENT", amount=2000, date=_last_month().isoformat())

    this_month = (await env.get(f"{EXPENSES}?period={month_key(business_today())}", token)).json()
    everything = (await env.get(f"{EXPENSES}?period=ALL", token)).json()

    assert this_month["summary"]["entryCount"] == 1
    assert everything["summary"]["entryCount"] == 2
    # "All periods" has no single period to label.
    assert everything["summary"]["period"] is None
    assert Decimal(str(everything["summary"]["totalAmount"])) == Decimal(3000)


async def test_a_date_range_narrows_inside_a_period(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)
    today = business_today()
    await created_expense(env, token, category="FUEL", date=today.isoformat())
    await created_expense(env, token, category="FUEL", date=(today - timedelta(days=20)).isoformat())

    recent = (await env.get(f"{EXPENSES}?from={(today - timedelta(days=5))}&to={today}", token)).json()

    assert recent["summary"]["entryCount"] == 1


async def test_search_matches_the_note_or_the_category_name(env):
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)

    by_note = (await env.get(f"{EXPENSES}?search=Brake", token)).json()
    by_category = (await env.get(f"{EXPENSES}?search=Utilities", token)).json()

    assert by_note["summary"]["entryCount"] == 1
    assert by_note["items"][0]["note"] == "Brake service - MP09 HT 7730"
    assert by_category["summary"]["entryCount"] == 1


async def test_paging_carries_both_vocabularies(env):
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)

    page_two = (await env.get(f"{EXPENSES}?page=2&pageSize=2", token)).json()

    assert page_two["page"] == 2
    assert page_two["pageSize"] == 2
    assert page_two["offset"] == 2
    assert page_two["limit"] == 2
    assert page_two["total"] == 5
    assert len(page_two["items"]) == 2


@pytest.mark.parametrize("period", ["2026-13", "September", "26-09", "2026/09"])
async def test_a_malformed_period_is_a_422_not_an_empty_list(env, period):
    """An empty list would look like "no spend this month", which is a lie."""
    token, _merchant, _user = await expense_staff(env)

    response = await env.get(f"{EXPENSES}?period={period}", token)

    assert response.status_code == 422, response.text
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == "period"


async def test_a_reversed_date_range_is_rejected(env):
    token, _merchant, _user = await expense_staff(env)

    response = await env.get(f"{EXPENSES}?from=2026-09-30&to=2026-09-01", token)

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["code"] == "date_range_reversed"


async def test_the_list_is_scoped_to_the_acting_merchant(env):
    theirs, _their_merchant, _their_user = await expense_staff(env)
    await created_expense(env, theirs, amount=99999)
    ours, _merchant, _user = await expense_staff(env)

    body = (await env.get(f"{EXPENSES}?period=ALL", ours)).json()

    assert body["summary"]["entryCount"] == 0
    assert Decimal(str(body["summary"]["totalAmount"])) == Decimal(0)


# --- Period chips ---------------------------------------------------------------------------


async def test_periods_list_every_month_with_its_own_total(env):
    token, _merchant, _user = await expense_staff(env)
    await categories(env, token)
    await created_expense(env, token, category="FUEL", amount=1000)
    await created_expense(env, token, category="RENT", amount=2000, date=_last_month().isoformat())

    periods = (await env.get(f"{EXPENSES}/periods", token)).json()

    assert [item["period"] for item in periods] == [month_key(business_today()), month_key(_last_month())]
    assert periods[0]["isCurrent"] is True
    assert Decimal(str(periods[0]["totalAmount"])) == Decimal(1000)
    assert periods[1]["label"] == "August 2026"


async def test_the_current_month_is_offered_even_when_empty(env):
    """The Add sheet files into it, so the screen needs somewhere to show the new row."""
    token, _merchant, _user = await expense_staff(env)

    periods = (await env.get(f"{EXPENSES}/periods", token)).json()

    assert periods[0]["period"] == month_key(business_today())
    assert periods[0]["entryCount"] == 0
    assert periods[0]["isCurrent"] is True


# --- Breakdown ------------------------------------------------------------------------------


async def test_the_breakdown_totals_each_category_biggest_first(env):
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)

    body = (await env.get(f"{EXPENSES}/breakdown?period={month_key(business_today())}", token)).json()

    assert Decimal(str(body["totalAmount"])) == Decimal(28550)
    assert body["entryCount"] == 5
    assert next(row["code"] for row in body["categories"]) == "VEHICLE_MAINTENANCE"
    fuel = next(row for row in body["categories"] if row["code"] == "FUEL")
    assert fuel["entryCount"] == 2
    assert Decimal(str(fuel["totalAmount"])) == Decimal(8100)


async def test_the_shares_add_up(env):
    token, _merchant, _user = await expense_staff(env)
    await _seed_month(env, token)

    body = (await env.get(f"{EXPENSES}/breakdown", token)).json()

    assert round(sum(row["sharePercent"] for row in body["categories"])) == 100


async def test_an_empty_breakdown_does_not_divide_by_zero(env):
    token, _merchant, _user = await expense_staff(env)

    body = (await env.get(f"{EXPENSES}/breakdown", token)).json()

    assert body["categories"] == []
    assert Decimal(str(body["totalAmount"])) == Decimal(0)
    assert body["entryCount"] == 0


async def test_reports_need_expenses_view(env):
    token, _merchant, _user = await expense_staff(env, permissions=("customers.view",))

    periods = await env.get(f"{EXPENSES}/periods", token)
    breakdown = await env.get(f"{EXPENSES}/breakdown", token)

    assert periods.status_code == 403
    assert breakdown.status_code == 403
