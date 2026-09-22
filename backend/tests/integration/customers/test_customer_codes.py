"""Concurrency-safe allocation of customer display codes."""

import asyncio

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from tests.integration.authentication.conftest import random_mobile
from tests.integration.customers.conftest import MERCHANT, registration_body, reviewer

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_codes_are_sequential_and_unique_per_type(env):
    token, _, _ = await reviewer(env)
    codes = []
    for customer_type in ("RETAIL", "RETAIL", "INDUSTRIAL"):
        mobile = random_mobile()
        body = await registration_body(env, MERCHANT, token, customer_type=customer_type, mobile=mobile.removeprefix("+91"))
        if customer_type == "INDUSTRIAL":
            from tests.integration.customers.conftest import site

            body["sites"] = [site()]
        response = await env.post(f"{MERCHANT}/customers", token, json=body)
        assert response.status_code == 201, response.text
        codes.append(response.json()["code"])

    assert len(set(codes)) == 3
    retail = [int(code.rsplit("-", 1)[1]) for code in codes[:2]]
    assert retail[1] == retail[0] + 1
    assert codes[2].startswith("MBGA-I-")


async def test_concurrent_creates_never_share_a_code(env):
    """Four staff adding customers at once. A MAX+1 scan would hand out duplicates."""
    token, merchant, _ = await reviewer(env)
    bodies = []
    for _ in range(4):
        mobile = random_mobile()
        bodies.append(await registration_body(env, MERCHANT, token, mobile=mobile.removeprefix("+91")))

    responses = await asyncio.gather(
        *(env.post(f"{MERCHANT}/customers", token, json=body) for body in bodies),
        return_exceptions=True,
    )
    created = [r for r in responses if not isinstance(r, Exception) and r.status_code == 201]
    assert len(created) == 4, [getattr(r, "text", r) for r in responses]

    codes = [r.json()["code"] for r in created]
    assert len(set(codes)) == 4, codes

    stored = await env.scalar(
        select(CustomerProfile.id).where(CustomerProfile.merchant_id == merchant.id, CustomerProfile.code.is_(None))
    )
    assert stored is None, "every created customer must have been given a code"
