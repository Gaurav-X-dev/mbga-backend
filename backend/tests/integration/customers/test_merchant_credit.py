"""Merchant credit controls stay permission- and tenant-scoped."""

import pytest

from tests.integration.authentication.conftest import code_of
from tests.integration.customers.conftest import MERCHANT, reviewer
from tests.integration.customers.test_merchant_customers import create_customer

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_authorised_merchant_can_update_own_customer_credit(env):
    token, _, _ = await reviewer(
        env, permissions=("customers.view", "customers.create", "credit.manage")
    )
    _, created = await create_customer(env, token)
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    updated = await env.client.patch(
        f"{MERCHANT}/credit/customers/{customer_id}",
        json={
            "creditEnabled": True,
            "creditLimit": 25000,
            "creditDays": 15,
            "reason": "Approved by agency owner",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "customerId": customer_id,
        "creditEnabled": True,
        "creditLimit": 25000,
        "creditDays": 15,
        "usedCredit": 0,
        "availableCredit": 25000,
    }

    detail = await env.get(f"{MERCHANT}/customers/{customer_id}", token)
    assert detail.status_code == 200, detail.text
    assert detail.json()["creditEnabled"] is True
    assert detail.json()["creditLimit"] == 25000
    assert detail.json()["creditDays"] == 15
    assert detail.json()["usedCredit"] == 0
    assert detail.json()["availableCredit"] == 25000


async def test_merchant_cannot_update_another_merchants_customer(env):
    token, _, _ = await reviewer(
        env, permissions=("customers.view", "customers.create", "credit.manage")
    )
    other_token, _, _ = await reviewer(
        env, permissions=("customers.view", "customers.create", "credit.manage")
    )
    _, other_customer = await create_customer(env, other_token)

    response = await env.client.patch(
        f"{MERCHANT}/credit/customers/{other_customer.json()['id']}",
        json={
            "creditEnabled": True,
            "creditLimit": 5000,
            "creditDays": 7,
            "reason": "Cross tenant attempt",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # Deliberately 404 so customer IDs cannot be probed across merchants.
    assert (response.status_code, code_of(response)) == (404, "CUSTOMER_NOT_FOUND")
