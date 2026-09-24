"""Pricing months, mid-month changes and the change log (spec endpoints 1-3)."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.pricing.constants import PricingMonthStatus
from app.modules.pricing.models import PricingChangeLog, PricingMonth
from tests.integration.pricing.conftest import (
    PRICING,
    code_of,
    current_month,
    entry_of,
    pricing_staff,
    put,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_first_read_opens_the_current_month_with_a_full_standard_card(env):
    token, _merchant, _user = await pricing_staff(env)

    month = await current_month(env, token)

    assert month["status"] == PricingMonthStatus.ACTIVE.value
    assert month["month"] == month["id"][-7:]
    assert month["effectiveFrom"][:7] == month["month"]
    assert {entry["cylinderType"] for entry in month["entries"]} == {
        "LPG_5KG",
        "LPG_19KG",
        "LPG_47_5KG_L",
        "LPG_47_5KG_V",
        "LPG_422KG_HIPPO",
    }
    assert all(entry["tier"] == "STANDARD" for entry in month["entries"])


async def test_amounts_are_json_numbers_and_timestamps_are_utc(env):
    """The app's types are `number` and a JS `Date`; a quoted amount would concatenate,
    and a timestamp with no zone would be read as local time and shown hours out."""
    token, _merchant, _user = await pricing_staff(env)

    month = await current_month(env, token)

    assert isinstance(month["gstPercent"], (int, float))
    for key in ("bpclBaseRate", "tierMarkup", "customerPrice"):
        assert isinstance(month["entries"][0][key], (int, float)), key
    assert month["updatedAt"].endswith("Z")


async def test_customer_price_is_computed_by_the_database_not_the_client(env):
    token, _merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)

    for entry in month["entries"]:
        expected = Decimal(str(entry["bpclBaseRate"])) + Decimal(str(entry["tierMarkup"]))
        assert Decimal(str(entry["customerPrice"])) == expected


async def test_reading_months_twice_does_not_open_a_second_month(env):
    token, merchant, _user = await pricing_staff(env)

    await current_month(env, token)
    await current_month(env, token)

    total = await env.scalar(
        select(PricingMonth).where(PricingMonth.merchant_id == merchant.id).order_by(PricingMonth.month)
    )
    months = (await env.get(f"{PRICING}/months", token)).json()
    assert total is not None
    assert len(months) == 1


async def test_a_mid_month_change_updates_the_entry_and_writes_one_log_row(env):
    token, merchant, user = await pricing_staff(env)
    month = await current_month(env, token)
    before = entry_of(month, "LPG_5KG")

    response = await put(
        env,
        f"{PRICING}/months/{month['id']}/entries",
        token,
        {
            "cylinderType": "LPG_5KG",
            "tier": "STANDARD",
            "bpclBaseRate": 458,
            "tierMarkup": 45,
            "reason": "BPCL base rate revised mid-month",
        },
    )

    assert response.status_code == 200, response.text
    after = entry_of(response.json(), "LPG_5KG")
    assert Decimal(str(after["bpclBaseRate"])) == Decimal(458)
    assert Decimal(str(after["customerPrice"])) == Decimal(503)
    assert response.json()["updatedBy"] == user.full_name

    log = await env.scalar(
        select(PricingChangeLog).where(
            PricingChangeLog.merchant_id == merchant.id,
            PricingChangeLog.cylinder_type == "LPG_5KG",
        )
    )
    assert log is not None
    assert log.old_bpcl_base_rate == Decimal(str(before["bpclBaseRate"]))
    assert log.old_customer_price == Decimal(str(before["customerPrice"]))
    assert log.new_customer_price == Decimal("503.00")
    assert log.reason == "BPCL base rate revised mid-month"
    # The acting user comes from the session, never from the body.
    assert log.changed_by_user_id == user.id
    assert log.changed_by_name == user.full_name
    assert log.changed_by_role == "MANAGER"


async def test_the_same_entry_can_be_changed_again_in_the_same_month(env):
    """The point of the slice: a rate is editable at any time, not only at a boundary."""
    token, _merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)
    path = f"{PRICING}/months/{month['id']}/entries"

    first = await put(env, path, token, {"cylinderType": "LPG_19KG", "bpclBaseRate": 1700, "tierMarkup": 110})
    second = await put(env, path, token, {"cylinderType": "LPG_19KG", "bpclBaseRate": 1725, "tierMarkup": 120})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert Decimal(str(entry_of(second.json(), "LPG_19KG")["customerPrice"])) == Decimal(1845)

    logs = (await env.get(f"{PRICING}/change-logs?cylinderType=LPG_19KG", token)).json()
    assert logs["total"] == 2
    # Newest first, and the second change's "old" values are the first change's "new" ones.
    assert Decimal(str(logs["items"][0]["oldBpclBaseRate"])) == Decimal(1700)
    assert Decimal(str(logs["items"][0]["newBpclBaseRate"])) == Decimal(1725)


async def test_change_log_carries_the_acting_user_and_pages_as_documented(env):
    token, _merchant, user = await pricing_staff(env)
    month = await current_month(env, token)
    path = f"{PRICING}/months/{month['id']}/entries"
    for rate in (446, 447, 448):
        assert (await put(env, path, token, {"cylinderType": "LPG_5KG", "bpclBaseRate": rate, "tierMarkup": 45})).status_code == 200

    page = (await env.get(f"{PRICING}/change-logs?page=1&pageSize=2", token)).json()

    assert page["page"] == 1
    assert page["pageSize"] == 2
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["id"].startswith("PRCLOG-")
    assert page["items"][0]["changedBy"] == {"id": user.id, "name": user.full_name, "role": "MANAGER"}


async def test_change_log_is_scoped_to_the_acting_merchant(env):
    ours, _merchant, _user = await pricing_staff(env)
    theirs, _other_merchant, _other_user = await pricing_staff(env)
    their_month = await current_month(env, theirs)
    await put(
        env,
        f"{PRICING}/months/{their_month['id']}/entries",
        theirs,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 999, "tierMarkup": 1},
    )

    ours_logs = (await env.get(f"{PRICING}/change-logs", ours)).json()

    assert ours_logs["total"] == 0


async def test_another_merchants_month_is_not_found_rather_than_forbidden(env):
    _theirs, _other_merchant, _other_user = await pricing_staff(env)
    ours, _merchant, _user = await pricing_staff(env)
    theirs_token, _m, _u = await pricing_staff(env)
    their_month = await current_month(env, theirs_token)

    response = await put(
        env,
        f"{PRICING}/months/{their_month['id']}/entries",
        ours,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 500, "tierMarkup": 10},
    )

    assert response.status_code == 404
    assert code_of(response) == "NOT_FOUND"


async def test_an_archived_month_is_a_conflict(env):
    token, merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)
    await env.execute(
        PricingMonth.__table__.update()
        .where(PricingMonth.__table__.c.id == month["id"])
        .values(status=PricingMonthStatus.ARCHIVED.value)
    )

    response = await put(
        env,
        f"{PRICING}/months/{month['id']}/entries",
        token,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 500, "tierMarkup": 10},
    )

    assert response.status_code == 409
    assert code_of(response) == "CONFLICT"
    assert merchant.id


async def test_an_unknown_month_is_not_found(env):
    token, _merchant, _user = await pricing_staff(env)

    response = await put(
        env,
        f"{PRICING}/months/PRC-NOPE-2026-01/entries",
        token,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 500, "tierMarkup": 10},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"cylinderType": "LPG_5KG", "bpclBaseRate": 0, "tierMarkup": 45}, "bpclBaseRate"),
        ({"cylinderType": "LPG_5KG", "bpclBaseRate": -1, "tierMarkup": 45}, "bpclBaseRate"),
        ({"cylinderType": "LPG_5KG", "bpclBaseRate": 445, "tierMarkup": -1}, "tierMarkup"),
        (
            {"cylinderType": "LPG_5KG", "bpclBaseRate": 445, "tierMarkup": 45, "effectiveFrom": "2020-01-01"},
            "effectiveFrom",
        ),
    ],
)
async def test_invalid_amounts_and_backdating_are_rejected(env, body, field):
    token, _merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)

    response = await put(env, f"{PRICING}/months/{month['id']}/entries", token, body)

    assert response.status_code == 422, response.text
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == field


async def test_a_zero_markup_is_allowed(env):
    """Selling at the BPCL base rate is a real decision, not a validation failure."""
    token, _merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)

    response = await put(
        env,
        f"{PRICING}/months/{month['id']}/entries",
        token,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 445, "tierMarkup": 0},
    )

    assert response.status_code == 200, response.text
    assert Decimal(str(entry_of(response.json(), "LPG_5KG")["customerPrice"])) == Decimal(445)


async def test_an_unknown_cylinder_type_is_rejected(env):
    token, _merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)

    response = await put(
        env,
        f"{PRICING}/months/{month['id']}/entries",
        token,
        {"cylinderType": "LPG_1KG", "bpclBaseRate": 100, "tierMarkup": 10},
    )

    assert response.status_code == 422


async def test_reading_needs_pricing_view_and_writing_needs_pricing_manage(env):
    read_only, merchant, _user = await pricing_staff(env, permissions=("pricing.view",))
    month = await current_month(env, read_only)

    blocked = await put(
        env,
        f"{PRICING}/months/{month['id']}/entries",
        read_only,
        {"cylinderType": "LPG_5KG", "bpclBaseRate": 500, "tierMarkup": 10},
    )

    assert blocked.status_code == 403
    assert merchant.id


async def test_staff_without_any_pricing_permission_cannot_read(env):
    token, _merchant, _user = await pricing_staff(env, permissions=("customers.view",))

    response = await env.get(f"{PRICING}/months", token)

    assert response.status_code == 403


async def test_pricing_requires_a_session(env):
    response = await env.get(f"{PRICING}/months")

    assert response.status_code == 401
