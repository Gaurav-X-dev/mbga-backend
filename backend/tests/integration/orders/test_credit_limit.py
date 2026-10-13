"""Trade-credit guard regressions for customer order placement."""

import asyncio

import pytest
from sqlalchemy import update

from app.modules.credit.service import CreditLimitService
from app.modules.customers.models import CustomerProfile
from app.modules.platform_settings.models import SINGLETON_ID, PlatformSettings
from tests.integration.deliveries.conftest import price_cylinders
from tests.integration.orders.conftest import (
    CUSTOMER_ORDERS,
    ORDERS,
    basket,
    customer_token,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def _configure(env, customer, *, enabled: bool, limit: int) -> None:
    await env.execute(
        update(PlatformSettings)
        .where(PlatformSettings.id == SINGLETON_ID)
        .values(credit_limit_enabled=enabled)
    )
    await env.execute(
        update(CustomerProfile)
        .where(CustomerProfile.id == customer.id)
        .values(credit_enabled=True, credit_limit=limit)
    )


async def _arrange(env):
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await price_cylinders(env, merchant, staff)
    token = await customer_token(env, customer)
    payload = {
        "customerId": customer.id,
        "items": basket(("LPG_19KG", 1)),
        "orderMode": "NEW",
    }
    quote = await post(env, f"{CUSTOMER_ORDERS}/quote", token, payload)
    assert quote.status_code == 200, quote.text
    return staff, merchant, customer, token, payload, quote.json()["totalAmount"]


@pytest.mark.asyncio
async def test_feature_off_is_identical_to_existing_customer_order_flow(env):
    _staff, _merchant, customer, token, payload, amount = await _arrange(env)
    await _configure(env, customer, enabled=False, limit=max(amount - 1, 0))

    response = await post(env, CUSTOMER_ORDERS, token, payload)

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_exactly_equal_limit_is_allowed_but_one_rupee_less_is_blocked(env):
    _staff, merchant, customer, token, payload, amount = await _arrange(env)
    await _configure(env, customer, enabled=True, limit=amount)
    allowed = await post(env, CUSTOMER_ORDERS, token, payload)
    assert allowed.status_code == 201, allowed.text

    other = await make_customer(env, merchant)
    # Use a fresh customer: the first accepted order correctly consumes the original limit.
    other_token = await customer_token(env, other)
    await _configure(env, other, enabled=True, limit=amount - 1)
    blocked_payload = {**payload, "customerId": other.id}
    blocked = await post(env, CUSTOMER_ORDERS, other_token, blocked_payload)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"
    assert "Available:" in blocked.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_merchant_created_order_is_credit_blocked(env):
    staff, _merchant, customer, _token, payload, _amount = await _arrange(env)
    await _configure(env, customer, enabled=True, limit=1)

    response = await post(env, ORDERS, staff, payload)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_customer_repeat_and_reorder_use_the_same_credit_guard(env):
    staff, _merchant, customer, token, payload, amount = await _arrange(env)
    original = await post(env, ORDERS, staff, payload)
    assert original.status_code == 201, original.text
    await _configure(env, customer, enabled=True, limit=amount)

    repeat = await post(env, f"{CUSTOMER_ORDERS}/repeat", token)
    reorder = await post(
        env,
        f"{CUSTOMER_ORDERS}/{original.json()['id']}/reorder",
        token,
        {},
    )

    assert repeat.status_code == 409
    assert repeat.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"
    assert reorder.status_code == 409
    assert reorder.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_credit_check_failure_is_fail_open(env, monkeypatch):
    _staff, _merchant, customer, token, payload, amount = await _arrange(env)
    await _configure(env, customer, enabled=True, limit=amount - 1)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("credit store unavailable")

    monkeypatch.setattr(CreditLimitService, "snapshot", broken)
    response = await post(env, CUSTOMER_ORDERS, token, payload)

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_notification_failure_does_not_change_credit_refusal(env, monkeypatch):
    _staff, _merchant, customer, token, payload, amount = await _arrange(env)
    await _configure(env, customer, enabled=True, limit=amount - 1)

    async def broken_notification(*_args, **_kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(CreditLimitService, "_queue_blocked", broken_notification)
    response = await post(env, CUSTOMER_ORDERS, token, payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_two_simultaneous_orders_cannot_both_spend_one_order_limit(env):
    _staff, _merchant, customer, token, payload, amount = await _arrange(env)
    await _configure(env, customer, enabled=True, limit=amount)

    first, second = await asyncio.gather(
        post(env, CUSTOMER_ORDERS, token, payload),
        post(env, CUSTOMER_ORDERS, token, payload),
    )

    assert sorted((first.status_code, second.status_code)) == [201, 409]
