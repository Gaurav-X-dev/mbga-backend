"""Who a row says did it.

`changed_by_name` is copied onto the row at the time, so an actor resolved with the wrong
name is wrong for ever - no later fix reaches back. That makes this worth pinning: a
customer's `users` row is created at their first OTP request, before they have told us who
they are, so the obvious read of `full_name` gives "Unknown user" on every row a
self-registered customer touches.
"""

import pytest
from sqlalchemy import select

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import CustomerProfile
from app.modules.orders.models import OrderStatusHistory
from app.modules.users.models import User
from app.shared.authorization.context import AuthContext
from app.shared.business.actor import BusinessActorResolver
from tests.integration.orders.conftest import (
    CUSTOMER_ORDERS,
    basket,
    created_order,
    customer_token,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

PLACEHOLDER = "Unknown user"


async def _history(env, order_id: str) -> list[OrderStatusHistory]:
    rows = await env.execute(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.id)
    )
    return [row[0] for row in rows]


async def _blank_the_login(env, profile: CustomerProfile) -> None:
    """Put the customer back in the state their first OTP request leaves them in."""
    await env.execute(
        User.__table__.update()
        .where(User.__table__.c.id == select(CustomerProfile.user_id)
               .where(CustomerProfile.id == profile.id).scalar_subquery())
        .values(full_name=None)
    )


async def test_staff_are_named_from_their_own_login(env):
    token, merchant, user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    assert (await _history(env, order["id"]))[0].changed_by_name == user.full_name


async def test_a_customer_with_no_name_on_their_login_is_still_named(env):
    """The regression: their name is in the profile, so it must never read "Unknown user"."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)
    await _blank_the_login(env, customer)

    placed = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {"customerId": customer.id, "items": basket(("LPG_19KG", 1)), "orderMode": "NEW"},
    )

    assert placed.status_code == 201, placed.text
    stamped = (await _history(env, placed.json()["id"]))[0].changed_by_name
    assert stamped != PLACEHOLDER
    # The person, not the business: "cancelled by Ravi Kumar", not "by Sharma Bakery".
    assert stamped == customer.owner_name
    assert staff


async def test_a_cancellation_is_named_too(env):
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)
    await _blank_the_login(env, customer)
    order = await created_order(env, staff, customer.id)

    cancelled = await post(env, f"{CUSTOMER_ORDERS}/{order['id']}/cancel", token)

    assert cancelled.status_code == 200, cancelled.text
    names = [row.changed_by_name for row in await _history(env, order["id"])]
    assert PLACEHOLDER not in names
    assert names[-1] == customer.owner_name


async def test_the_business_name_is_the_fallback_when_no_owner_is_recorded(env):
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)
    await _blank_the_login(env, customer)
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(owner_name=None)
    )

    placed = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {"customerId": customer.id, "items": basket(("LPG_19KG", 1)), "orderMode": "NEW"},
    )

    assert placed.status_code == 201, placed.text
    assert (await _history(env, placed.json()["id"]))[0].changed_by_name == customer.name
    assert staff


async def test_a_name_already_on_the_login_is_not_overridden_by_the_profile(env):
    """An admin who set a name deliberately must keep it."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)

    placed = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {"customerId": customer.id, "items": basket(("LPG_19KG", 1)), "orderMode": "NEW"},
    )

    # `customer_token` creates the login with the owner's name, so both agree here - what
    # matters is that a real name is used rather than the placeholder.
    assert (await _history(env, placed.json()["id"]))[0].changed_by_name != PLACEHOLDER
    assert staff


async def test_the_resolver_prefers_the_profile_over_an_empty_login(env):
    """The unit-level version: no HTTP, just the actor that every write is stamped from."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await customer_token(env, customer)
    await _blank_the_login(env, customer)

    async with env.sessions() as session:
        user_id = await session.scalar(
            select(CustomerProfile.user_id).where(CustomerProfile.id == customer.id)
        )
        actor = await BusinessActorResolver(session).resolve(
            AuthContext(
                user_id=user_id,
                login_channel=LoginChannel.CUSTOMER,
                session_id="s-1",
                token_type="access",
            )
        )

    assert actor.display_name == customer.owner_name
    assert actor.customer_id == customer.id
    assert staff
