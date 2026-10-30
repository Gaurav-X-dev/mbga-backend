"""Telling the assignment screen a van is taken, before it presses Confirm.

Reported from the panel: the vehicle dropdown offered GY45GB2268, the operator picked it, and
the Confirm button came back with "GY45GB2268 is already out with Aryan Nara today." The rule
was right; it just fired at the wrong moment, after the form was filled.

The picker could not have known. `available_for_pincode` asked three questions - is the van
this merchant's, is it active, does it serve this pincode - and none of them is about today.

What it must *not* do is drop the busy van from the list. The rule is one van, one driver, one
day, so a van already out only clashes for a **different** driver; the same driver filling a
round through the morning is the ordinary case and stays allowed. Hiding the row would block
the assignment that is actually correct. So the row stays and carries who has it.
"""

import pytest

from tests.integration.deliveries.conftest import (  # noqa: F401 - fixtures
    DELIVERIES,
    ORDERS,
    env,
    make_driver,
    place_order,
    ready_to_dispatch,
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

VAN = "MP09 GH 4521"


async def vehicles_for(env, token: str, order_id: str) -> list[dict]:
    response = await env.get(f"{ORDERS}/{order_id}/available-vehicles", token)
    assert response.status_code == 200, response.text
    return response.json()


def row_for(rows: list[dict], number: str) -> dict:
    return next(row for row in rows if row["number"] == number)


# --- A van already out ---------------------------------------------------------------------------


async def test_a_free_van_says_nobody_has_it(env):
    token, _merchant, order, _slip, _driver = await ready_to_dispatch(env, with_driver=False)

    rows = await vehicles_for(env, token, order["id"])

    assert rows, "no vehicle mapped to the order's pincode"
    assert all(row["busyWithDriverName"] is None for row in rows)


async def test_a_taken_van_names_its_driver(env):
    """The sentence the operator used to only see after pressing Confirm."""
    token, merchant, _order, slip, driver = await ready_to_dispatch(env)
    second = await place_order(env, token, slip["customerId"], ("LPG_19KG", 1))

    rows = await vehicles_for(env, token, second["id"])

    taken = row_for(rows, slip["vehicleNumber"])
    assert taken["busyWithDriverName"] is not None
    assert taken["busyWithDriverUserId"] == driver.id


async def test_the_taken_van_is_still_listed(env):
    """Because the same driver may take it out again - that is a round, not a clash."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    second = await place_order(env, token, slip["customerId"], ("LPG_19KG", 1))

    rows = await vehicles_for(env, token, second["id"])

    assert slip["vehicleNumber"] in {row["number"] for row in rows}


# --- What does not count as taken ------------------------------------------------------------------


async def test_a_hired_van_with_no_driver_holds_nothing(env):
    """Nobody to clash with, and a hired van is a different vehicle each time."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env, with_driver=False)
    second = await place_order(env, token, slip["customerId"], ("LPG_19KG", 1))

    rows = await vehicles_for(env, token, second["id"])

    assert row_for(rows, slip["vehicleNumber"])["busyWithDriverName"] is None


async def test_a_settled_round_frees_the_van(env):
    """Only live slips hold a van; a delivered one is finished with it."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    async with env.sessions() as db:
        from sqlalchemy import update

        from app.modules.deliveries.models import DeliverySlip

        await db.execute(
            update(DeliverySlip).where(DeliverySlip.id == slip["id"]).values(status="DELIVERED")
        )
        await db.commit()
    second = await place_order(env, token, slip["customerId"], ("LPG_19KG", 1))

    rows = await vehicles_for(env, token, second["id"])

    assert row_for(rows, slip["vehicleNumber"])["busyWithDriverName"] is None


async def test_another_days_round_does_not_hold_it(env):
    """One van, one driver, one *day*."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    async with env.sessions() as db:
        from datetime import timedelta

        from sqlalchemy import update

        from app.modules.deliveries.models import DeliverySlip
        from app.shared.date_time.business_calendar import business_today

        await db.execute(
            update(DeliverySlip)
            .where(DeliverySlip.id == slip["id"])
            .values(scheduled_date=business_today() + timedelta(days=3))
        )
        await db.commit()
    second = await place_order(env, token, slip["customerId"], ("LPG_19KG", 1))

    rows = await vehicles_for(env, token, second["id"])

    assert row_for(rows, slip["vehicleNumber"])["busyWithDriverName"] is None
