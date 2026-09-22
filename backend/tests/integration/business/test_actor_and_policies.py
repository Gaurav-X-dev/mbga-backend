"""Phase B: business actor resolution, merchant tenancy and customer ownership."""

from dataclasses import dataclass

import pytest
from sqlalchemy import select, update

from app.modules.authentication.constants import LoginChannel
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.business.policies import (
    ensure_customer_owns,
    ensure_merchant_owns,
    ensure_own_customer_id,
    ensure_visible,
    require_channel,
    scope_to_merchant,
)
from app.shared.exceptions.api_error import ApiError
from tests.integration.business.conftest import resolve_actor

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


@dataclass
class Row:
    """Stand-in for a domain row, so policy tests do not wait on Phase C models."""

    id: str
    merchant_id: str | None = None
    customer_id: str | None = None


# --- actor resolution ---------------------------------------------------------------


async def test_merchant_staff_resolve_to_their_merchant(env) -> None:
    user, merchant = await env.create_merchant_staff()

    async with env.sessions() as db:
        actor = await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert actor.merchant_id == merchant.id
    assert actor.merchant_code == merchant.code
    assert actor.is_merchant_staff
    assert not actor.is_customer


async def test_the_display_name_comes_from_the_account_not_the_request(env) -> None:
    user, _ = await env.create_merchant_staff()

    async with env.sessions() as db:
        actor = await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert actor.display_name == "Test Manager"
    # The mobile number must never leak into an actor field written onto a record.
    assert user.mobile_number not in actor.display_name


async def test_a_staff_account_with_no_merchant_link_is_denied(env) -> None:
    user = await env.create_user(roles=("manager",))

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert (error.value.status_code, error.value.code) == (403, "ROLE_NOT_ASSIGNED")


async def test_an_inactive_merchant_link_is_denied(env) -> None:
    user, _ = await env.create_merchant_staff(link_status="BLOCKED")

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert (error.value.status_code, error.value.code) == (403, "ACCOUNT_INACTIVE")


async def test_a_blocked_merchant_blocks_its_staff(env) -> None:
    user, merchant = await env.create_merchant_staff()
    await env.execute(update(Merchant).where(Merchant.id == merchant.id).values(status="BLOCKED"))

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert error.value.code == "MERCHANT_BLOCKED"


async def test_an_inactive_user_account_is_denied(env) -> None:
    user, _ = await env.create_merchant_staff()
    await env.execute(update(User).where(User.id == user.id).values(status="INACTIVE"))

    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await resolve_actor(db, user.id, LoginChannel.MERCHANT)

    assert error.value.code == "ACCOUNT_INACTIVE"


async def test_a_deleted_account_reads_as_signed_out(env) -> None:
    async with env.sessions() as db:
        with pytest.raises(ApiError) as error:
            await resolve_actor(db, "missing-user-id", LoginChannel.MERCHANT)

    assert (error.value.status_code, error.value.code) == (401, "SESSION_REVOKED")


async def test_a_customer_without_a_profile_still_resolves(env) -> None:
    """accountStatus NEW: signed in, not yet registered (spec §2)."""
    user = await env.create_user(roles=("customer",))

    async with env.sessions() as db:
        actor = await resolve_actor(db, user.id, LoginChannel.CUSTOMER)

    assert actor.is_customer
    assert actor.customer_id is None
    with pytest.raises(ApiError):
        actor.require_customer_id()


# --- tenancy and ownership ----------------------------------------------------------


def _merchant_actor(merchant_id: str) -> BusinessActor:
    return BusinessActor(
        user_id="u-1",
        login_channel=LoginChannel.MERCHANT,
        display_name="Staff",
        merchant_id=merchant_id,
    )


def _customer_actor(customer_id: str) -> BusinessActor:
    return BusinessActor(
        user_id="u-2",
        login_channel=LoginChannel.CUSTOMER,
        display_name="Buyer",
        customer_id=customer_id,
    )


def test_another_merchants_row_reads_as_not_found_not_forbidden() -> None:
    """403 would confirm the row exists, which lets a caller enumerate other tenants."""
    with pytest.raises(ApiError) as error:
        ensure_merchant_owns(Row(id="r1", merchant_id="other"), _merchant_actor("mine"))

    assert error.value.status_code == 404


def test_a_row_belonging_to_the_actors_merchant_is_returned() -> None:
    row = Row(id="r1", merchant_id="mine")
    assert ensure_merchant_owns(row, _merchant_actor("mine")) is row


def test_a_missing_row_and_a_foreign_row_are_indistinguishable() -> None:
    actor = _merchant_actor("mine")
    with pytest.raises(ApiError) as missing:
        ensure_merchant_owns(None, actor)
    with pytest.raises(ApiError) as foreign:
        ensure_merchant_owns(Row(id="r1", merchant_id="other"), actor)

    assert missing.value.status_code == foreign.value.status_code == 404
    assert missing.value.detail["code"] == foreign.value.detail["code"]
    assert missing.value.detail["message"] == foreign.value.detail["message"]


def test_a_customer_cannot_read_another_customers_row() -> None:
    with pytest.raises(ApiError) as error:
        ensure_customer_owns(Row(id="r1", customer_id="other"), _customer_actor("mine"))

    assert error.value.status_code == 404


def test_the_shared_visibility_rule_follows_the_actors_channel() -> None:
    """One handler, two apps: the channel picks the ownership rule."""
    shared = Row(id="r1", merchant_id="m1", customer_id="c1")

    assert ensure_visible(shared, _customer_actor("c1")) is shared
    assert ensure_visible(shared, _merchant_actor("m1")) is shared
    with pytest.raises(ApiError):
        ensure_visible(shared, _customer_actor("c-other"))
    with pytest.raises(ApiError):
        ensure_visible(shared, _merchant_actor("m-other"))


def test_a_customer_may_only_name_their_own_id_in_a_path() -> None:
    actor = _customer_actor("c1")
    assert ensure_own_customer_id("c1", actor) == "c1"
    with pytest.raises(ApiError) as error:
        ensure_own_customer_id("c2", actor)
    assert error.value.status_code == 404


def test_merchant_staff_may_name_any_id_and_the_row_load_decides() -> None:
    assert ensure_own_customer_id("c-any", _merchant_actor("m1")) == "c-any"


def test_a_list_query_is_filtered_to_the_actors_merchant() -> None:
    statement = scope_to_merchant(select(MerchantUser), MerchantUser.merchant_id, _merchant_actor("m-1"))
    assert "merchant_id" in str(statement.whereclause)


def test_a_session_from_another_app_is_rejected() -> None:
    with pytest.raises(ApiError) as error:
        require_channel(_customer_actor("c1"), LoginChannel.MERCHANT)

    assert (error.value.status_code, error.value.code) == (401, "TOKEN_CHANNEL_MISMATCH")


def test_the_right_channel_passes() -> None:
    require_channel(_merchant_actor("m1"), LoginChannel.MERCHANT)
