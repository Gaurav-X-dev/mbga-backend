"""The public constants endpoint, backed by the `constants` table."""

import pytest
from sqlalchemy import select, update

from app.modules.constants.models import Constant
from app.modules.constants.seeds import ConstantsSeedRunner, seed_rows
from app.modules.customers.constants import CustomerType, KycDocumentType, PricingTier
from app.modules.merchants.models import Merchant
from tests.integration.authentication.conftest import code_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

CUSTOMER = "/api/v1/customer/constants"
MERCHANT = "/api/v1/merchant/constants"


async def test_it_answers_without_any_token(env):
    """A customer picks their merchant before they have an account, so there is no token."""
    response = await env.client.get(CUSTOMER)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


async def test_every_row_has_the_same_four_fields(env):
    await env.create_merchant()
    rows = (await env.client.get(CUSTOMER)).json()
    assert rows
    for row in rows:
        assert set(row) == {"id", "constKey", "constValue", "constGroup"}, row
        assert all(row.values())


async def test_both_apps_get_the_same_rows(env):
    """One source, mounted twice, so the two apps can never drift apart."""
    assert (await env.client.get(CUSTOMER)).json() == (await env.client.get(MERCHANT)).json()


# --- the table is the source ------------------------------------------------------------


async def test_the_rows_come_from_the_constants_table(env):
    async with env.sessions() as db:
        stored = list(await db.scalars(select(Constant)))
    served = {r["constKey"] for r in (await env.client.get(CUSTOMER)).json()}
    for row in stored:
        assert row.const_key in served


async def test_a_label_edited_in_the_database_reaches_the_app(env):
    """The point of a table: reword a label without a deploy."""
    await env.execute(
        update(Constant).where(Constant.const_key == "RETAIL").values(const_value="Retail Shop")
    )
    rows = (await env.client.get(CUSTOMER, params={"group": "customerTypes"})).json()
    retail = next(r for r in rows if r["constKey"] == "RETAIL")
    assert retail["constValue"] == "Retail Shop"


async def test_a_group_can_be_asked_for_on_its_own(env):
    rows = (await env.client.get(CUSTOMER, params={"group": "documentTypes"})).json()
    assert {r["constKey"] for r in rows} == {t.value for t in KycDocumentType}
    assert {r["constGroup"] for r in rows} == {"documentTypes"}


async def test_an_unknown_group_is_simply_empty(env):
    assert (await env.client.get(CUSTOMER, params={"group": "colours"})).json() == []


# --- the keys must match what the API accepts ---------------------------------------------


@pytest.mark.parametrize(
    ("group", "enum"),
    [("customerTypes", CustomerType), ("documentTypes", KycDocumentType), ("pricingTiers", PricingTier)],
)
async def test_the_keys_are_exactly_what_the_write_endpoints_accept(env, group, enum):
    """An option the backend would reject is worse than no option at all."""
    keys = {r["constKey"] for r in (await env.client.get(CUSTOMER, params={"group": group})).json()}
    assert keys == {member.value for member in enum}


async def test_the_seeder_is_idempotent_and_keeps_edited_labels(env):
    await env.execute(
        update(Constant).where(Constant.const_key == "PAN").values(const_value="PAN Card (edited)")
    )
    async with env.sessions() as db:
        result = await ConstantsSeedRunner(db).run()
    assert result == {"constants_created": 0, "constants_repaired": 0}

    rows = (await env.client.get(CUSTOMER, params={"group": "documentTypes"})).json()
    assert next(r for r in rows if r["constKey"] == "PAN")["constValue"] == "PAN Card (edited)"


async def test_a_row_moved_to_the_wrong_group_is_put_back(env):
    """The group is what the app filters on, so a wrong one hides the option entirely."""
    await env.execute(update(Constant).where(Constant.const_key == "GST").values(const_group="wrong"))
    async with env.sessions() as db:
        assert (await ConstantsSeedRunner(db).run())["constants_repaired"] == 1

    keys = {r["constKey"] for r in (await env.client.get(CUSTOMER, params={"group": "documentTypes"})).json()}
    assert "GST" in keys


async def test_every_seeded_key_is_unique(env):
    keys = [seed.key for seed in seed_rows()]
    assert len(keys) == len(set(keys)), "a key is the app's handle for a row"


# --- merchants ------------------------------------------------------------------------------


async def test_merchants_are_served_in_the_same_shape(env):
    created = await env.create_merchant()
    rows = (await env.client.get(CUSTOMER, params={"group": "merchants"})).json()
    entry = next((r for r in rows if r["constKey"] == created.code), None)
    assert entry is not None, "a merchant added to the database must appear without a release"
    assert entry["constValue"] == created.name
    assert entry["constGroup"] == "merchants"


async def test_only_usable_merchants_are_offered(env):
    """Offering a blocked merchant would mean a registration accepted then rejected."""
    blocked = await env.create_merchant()
    await env.execute(update(Merchant).where(Merchant.id == blocked.id).values(status="BLOCKED"))
    unapproved = await env.create_merchant(approval_status="PENDING")

    keys = {r["constKey"] for r in (await env.client.get(CUSTOMER)).json()}
    assert blocked.code not in keys
    assert unapproved.code not in keys


async def test_the_internal_merchant_id_never_leaves(env):
    """The key is the display code; Merchant.id has no business reaching a public caller."""
    created = await env.create_merchant()
    raw = (await env.client.get(CUSTOMER)).text
    assert created.id not in raw
    for leaked in ("status", "approval_status", "merchant_id"):
        assert f'"{leaked}"' not in raw


async def test_the_merchant_options_are_sorted(env):
    """Spec 7.2 orders customers A-Z; the merchant picker follows the same convention."""
    await env.create_merchant()
    await env.create_merchant()
    names = [r["constValue"] for r in (await env.client.get(CUSTOMER, params={"group": "merchants"})).json()]
    assert names == sorted(names)


@pytest.mark.parametrize("settings_overrides", [{"constants_limit_per_ip": 3}], indirect=True)
async def test_a_public_endpoint_is_rate_limited(env):
    """Unauthenticated and cheap to call, so it needs the same per-IP limit as the others."""
    for _ in range(3):
        assert (await env.client.get(CUSTOMER)).status_code == 200

    limited = await env.client.get(CUSTOMER)
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")
