"""Per-customer price overrides (spec endpoints 4-6), and the downstream resolution rule."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.pricing.models import CustomerPriceOverride, CustomerPriceOverrideLog
from app.modules.pricing.service import resolve_customer_price
from tests.integration.pricing.conftest import (
    MERCHANT,
    code_of,
    create_customer,
    current_month,
    delete,
    entry_of,
    pricing_staff,
    put,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def _pricing_path(customer_id: str, cylinder_type: str | None = None) -> str:
    base = f"{MERCHANT}/customers/{customer_id}/pricing"
    return base if cylinder_type is None else f"{base}/{cylinder_type}"


def _item(body: dict, cylinder_type: str) -> dict:
    return next(item for item in body["items"] if item["cylinderType"] == cylinder_type)


async def test_a_retail_customer_is_priced_at_the_tier_card_with_no_override(env):
    token, merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)
    customer_id = await create_customer(env, merchant)

    response = await env.get(_pricing_path(customer_id), token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customerId"] == customer_id
    assert body["tier"] == "STANDARD"
    five_kg = _item(body, "LPG_5KG")
    assert five_kg["cylinderLabel"] == "5 KG Cylinder"
    assert Decimal(str(five_kg["tierPrice"])) == Decimal(str(entry_of(month, "LPG_5KG")["customerPrice"]))
    assert five_kg["override"] is None
    assert five_kg["effectivePrice"] == five_kg["tierPrice"]


async def test_hippo_is_offered_to_industrial_customers_only(env):
    token, merchant, _user = await pricing_staff(env)
    retail_id = await create_customer(env, merchant, customer_type="RETAIL")
    industrial_id = await create_customer(env, merchant, customer_type="INDUSTRIAL")

    retail = (await env.get(_pricing_path(retail_id), token)).json()
    industrial = (await env.get(_pricing_path(industrial_id), token)).json()

    assert "LPG_422KG_HIPPO" not in {item["cylinderType"] for item in retail["items"]}
    assert "LPG_422KG_HIPPO" in {item["cylinderType"] for item in industrial["items"]}


async def test_setting_an_override_changes_the_effective_price_and_logs_a_set(env):
    token, merchant, user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)

    response = await put(
        env,
        _pricing_path(customer_id, "LPG_5KG"),
        token,
        {"overridePrice": 470, "reason": "Loyalty discount"},
    )

    assert response.status_code == 200, response.text
    item = response.json()
    assert Decimal(str(item["effectivePrice"])) == Decimal(470)
    assert Decimal(str(item["override"]["overridePrice"])) == Decimal(470)
    assert item["override"]["reason"] == "Loyalty discount"
    assert item["override"]["setBy"] == user.full_name
    assert isinstance(item["effectivePrice"], (int, float))
    assert item["override"]["setAt"].endswith("Z")
    # The tier price is untouched - the override sits beside it, it does not replace it.
    assert item["tierPrice"] != item["effectivePrice"]

    log = await env.scalar(
        select(CustomerPriceOverrideLog).where(CustomerPriceOverrideLog.customer_id == customer_id)
    )
    assert log.action == "SET"
    assert log.old_override_price is None
    assert log.new_override_price == Decimal("470.00")
    assert log.changed_by_user_id == user.id
    assert log.changed_by_role == "MANAGER"


async def test_setting_it_again_updates_in_place_and_logs_an_update(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)
    path = _pricing_path(customer_id, "LPG_5KG")

    await put(env, path, token, {"overridePrice": 470})
    second = await put(env, path, token, {"overridePrice": 465, "reason": "Renegotiated"})

    assert second.status_code == 200, second.text
    assert Decimal(str(second.json()["effectivePrice"])) == Decimal(465)

    stored = list(
        await env.execute(
            select(CustomerPriceOverride.override_price).where(
                CustomerPriceOverride.customer_id == customer_id
            )
        )
    )
    assert stored == [(Decimal("465.00"),)], "the override is upserted, not duplicated"

    rows = list(
        await env.execute(
            select(CustomerPriceOverrideLog.action, CustomerPriceOverrideLog.old_override_price)
            .where(CustomerPriceOverrideLog.customer_id == customer_id)
            .order_by(CustomerPriceOverrideLog.id)
        )
    )
    assert [row[0] for row in rows] == ["SET", "UPDATE"]
    assert rows[1][1] == Decimal("470.00")


async def test_the_override_shows_on_the_customers_pricing_tab(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)
    await put(env, _pricing_path(customer_id, "LPG_5KG"), token, {"overridePrice": 470})

    body = (await env.get(_pricing_path(customer_id), token)).json()

    assert Decimal(str(_item(body, "LPG_5KG")["effectivePrice"])) == Decimal(470)
    # Only the one cylinder type is overridden; the rest still price at the tier.
    nineteen = _item(body, "LPG_19KG")
    assert nineteen["override"] is None
    assert nineteen["effectivePrice"] == nineteen["tierPrice"]


async def test_removing_the_override_reverts_to_the_tier_price_and_logs_a_remove(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)
    path = _pricing_path(customer_id, "LPG_5KG")
    await put(env, path, token, {"overridePrice": 470})

    response = await delete(env, path, token)

    assert response.status_code == 200, response.text
    item = response.json()
    assert item["override"] is None
    assert item["effectivePrice"] == item["tierPrice"]

    remaining = await env.scalar(
        select(CustomerPriceOverride).where(CustomerPriceOverride.customer_id == customer_id)
    )
    assert remaining is None

    rows = list(
        await env.execute(
            select(CustomerPriceOverrideLog.action, CustomerPriceOverrideLog.new_override_price)
            .where(CustomerPriceOverrideLog.customer_id == customer_id)
            .order_by(CustomerPriceOverrideLog.id)
        )
    )
    assert [row[0] for row in rows] == ["SET", "REMOVE"]
    assert rows[1][1] is None


async def test_removing_an_override_that_is_not_there_is_not_found(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)

    response = await delete(env, _pricing_path(customer_id, "LPG_5KG"), token)

    assert response.status_code == 404


async def test_an_override_applies_everywhere_the_customer_is_priced(env):
    """The downstream rule: quoting and billing read the same resolved number."""
    token, merchant, _user = await pricing_staff(env)
    month = await current_month(env, token)
    customer_id = await create_customer(env, merchant)
    tier_price = Decimal(str(entry_of(month, "LPG_5KG")["customerPrice"]))
    await put(env, _pricing_path(customer_id, "LPG_5KG"), token, {"overridePrice": 470})

    async with env.sessions() as session:
        overridden = await resolve_customer_price(session, customer_id, "LPG_5KG", tier_price)
        untouched = await resolve_customer_price(session, customer_id, "LPG_19KG", Decimal(1800))

    assert overridden == Decimal("470.00")
    assert untouched == Decimal(1800)


async def test_a_price_of_zero_or_less_is_rejected(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)

    response = await put(env, _pricing_path(customer_id, "LPG_5KG"), token, {"overridePrice": 0})

    assert response.status_code == 422
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == "overridePrice"


async def test_backdating_an_override_is_rejected(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    customer_id = await create_customer(env, merchant)

    response = await put(
        env,
        _pricing_path(customer_id, "LPG_5KG"),
        token,
        {"overridePrice": 470, "effectiveFrom": "2020-01-01"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "effectiveFrom"


async def test_a_cylinder_the_customer_cannot_order_is_not_found(env):
    token, merchant, _user = await pricing_staff(env)
    await current_month(env, token)
    retail_id = await create_customer(env, merchant, customer_type="RETAIL")

    response = await put(env, _pricing_path(retail_id, "LPG_422KG_HIPPO"), token, {"overridePrice": 30000})

    assert response.status_code == 404


async def test_an_unknown_cylinder_type_in_the_path_is_rejected(env):
    token, merchant, _user = await pricing_staff(env)
    customer_id = await create_customer(env, merchant)

    response = await put(env, _pricing_path(customer_id, "LPG_1KG"), token, {"overridePrice": 100})

    assert response.status_code == 422


async def test_another_merchants_customer_is_not_found(env):
    _theirs, their_merchant, _their_user = await pricing_staff(env)
    their_customer = await create_customer(env, their_merchant)
    ours, _merchant, _user = await pricing_staff(env)

    read = await env.get(_pricing_path(their_customer), ours)
    write = await put(env, _pricing_path(their_customer, "LPG_5KG"), ours, {"overridePrice": 470})

    assert read.status_code == 404
    assert write.status_code == 404
    assert code_of(read) == "CUSTOMER_NOT_FOUND"


async def test_setting_a_price_needs_pricing_manage(env):
    token, merchant, _user = await pricing_staff(
        env, permissions=("pricing.view", "customers.create", "customers.view")
    )
    customer_id = await create_customer(env, merchant)

    readable = await env.get(_pricing_path(customer_id), token)
    blocked = await put(env, _pricing_path(customer_id, "LPG_5KG"), token, {"overridePrice": 470})

    assert readable.status_code == 200
    assert blocked.status_code == 403
