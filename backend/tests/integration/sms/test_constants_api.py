"""The public constants endpoint the apps fill their dropdowns from."""

import pytest
from sqlalchemy import update

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


async def test_every_entry_is_exactly_a_key_and_a_value(env):
    """One shape for the whole response, so the app has a single parser."""
    await env.create_merchant()
    options = (await env.client.get(CUSTOMER)).json()
    assert options
    for option in options:
        assert set(option) == {"key", "value"}, option
        assert option["key"] and option["value"]


async def test_both_apps_get_the_same_list(env):
    """One source, mounted twice, so the two apps can never drift apart."""
    assert (await env.client.get(CUSTOMER)).json() == (await env.client.get(MERCHANT)).json()


async def test_the_merchant_options_come_from_the_database(env):
    created = await env.create_merchant()
    options = (await env.client.get(CUSTOMER)).json()
    entry = next((o for o in options if o["key"] == created.code), None)
    assert entry is not None, "a merchant added to the database must appear without a release"
    assert entry["value"] == created.name


async def test_only_usable_merchants_are_offered(env):
    """Offering a blocked merchant would mean a registration accepted then rejected."""
    blocked = await env.create_merchant()
    await env.execute(update(Merchant).where(Merchant.id == blocked.id).values(status="BLOCKED"))
    unapproved = await env.create_merchant(approval_status="PENDING")

    keys = {o["key"] for o in (await env.client.get(CUSTOMER)).json()}
    assert blocked.code not in keys
    assert unapproved.code not in keys


async def test_the_fixed_vocabularies_are_all_present(env):
    keys = {o["key"] for o in (await env.client.get(CUSTOMER)).json()}
    assert {t.value for t in CustomerType} <= keys
    assert {t.value for t in KycDocumentType} <= keys
    assert {t.value for t in PricingTier} <= keys


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("customerTypes", {t.value for t in CustomerType}),
        ("documentTypes", {t.value for t in KycDocumentType}),
        ("pricingTiers", {t.value for t in PricingTier}),
    ],
)
async def test_one_set_can_be_asked_for_on_its_own(env, type_name, expected):
    """A flat list carries no grouping, so `?type=` is how a screen gets just its own set.

    These keys are also exactly what the write endpoints accept - an option the backend would
    reject is worse than no option at all.
    """
    options = (await env.client.get(CUSTOMER, params={"type": type_name})).json()
    assert {o["key"] for o in options} == expected


async def test_an_unknown_type_is_refused_by_name(env):
    response = await env.client.get(CUSTOMER, params={"type": "colours"})
    assert (response.status_code, code_of(response)) == (422, "VALIDATION_ERROR")
    assert response.json()["detail"]["fields"][0]["field"] == "type"


async def test_no_internal_identifier_ever_leaves(env):
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
    names = [o["value"] for o in (await env.client.get(CUSTOMER, params={"type": "merchants"})).json()]
    assert names == sorted(names)


@pytest.mark.parametrize("settings_overrides", [{"constants_limit_per_ip": 3}], indirect=True)
async def test_a_public_endpoint_is_rate_limited(env):
    """Unauthenticated and cheap to call, so it needs the same per-IP limit as the others."""
    for _ in range(3):
        assert (await env.client.get(CUSTOMER)).status_code == 200

    limited = await env.client.get(CUSTOMER)
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")
