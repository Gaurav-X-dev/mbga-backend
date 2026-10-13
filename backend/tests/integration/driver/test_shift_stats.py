"""The counters on the driver's own profile.

`shiftStats` greets a driver with what they have done: how many deliveries today, how many ever,
what they have collected and how many shells came back. Until now only the empty case was
tested - a brand new driver sees zeroes - and nothing checked the numbers after an actual
round, which is the only state a real driver ever sees them in.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.modules.deliveries.models import DeliverySlip
from app.shared.date_time.business_calendar import business_today
from tests.integration.driver.conftest import (  # noqa: F401 - fixtures
    DRIVER,
    env,
    settings_overrides,
)
from tests.integration.driver.test_customer_empties import a_customer, complete, visit

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def stats(env, drivers) -> dict:
    response = await env.get(f"{DRIVER}/profile", drivers)
    assert response.status_code == 200, response.text
    return response.json()["shiftStats"]


async def scheduled_for(env, slip_id: str, days_ago: int) -> None:
    """Move the day the round was planned for, leaving when it happened alone."""
    async with env.sessions() as db:
        await db.execute(
            update(DeliverySlip)
            .where(DeliverySlip.id == slip_id)
            .values(scheduled_date=business_today() - timedelta(days=days_ago))
        )
        await db.commit()


async def happened_days_ago(env, slip_id: str, days: int) -> None:
    """Move when the handover actually took place, which is what the counters read."""
    async with env.sessions() as db:
        await db.execute(
            update(DeliverySlip)
            .where(DeliverySlip.id == slip_id)
            .values(
                scheduled_date=business_today() - timedelta(days=days),
                delivered_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days),
            )
        )
        await db.commit()


# --- What the numbers count ----------------------------------------------------------------------


async def test_a_completed_round_is_counted(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    await complete(env, drivers, slip_id, otp, [("LPG_19KG", 2)], [])

    today = await stats(env, drivers)
    assert today["completedDeliveriesToday"] == 1
    assert today["totalCompletedDeliveries"] == 1


async def test_two_rounds_count_twice(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])
    _d, second, otp2 = await visit(env, token, customer, driver, ("LPG_19KG", 1))

    await complete(env, drivers, second, otp2, [("LPG_19KG", 1)], [])

    assert (await stats(env, drivers))["completedDeliveriesToday"] == 2


async def test_a_delivery_still_on_the_van_is_not_counted(env):
    """It has not happened yet."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, _slip, _otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    assert (await stats(env, drivers))["completedDeliveriesToday"] == 0


async def test_another_drivers_round_is_not_counted(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, slip_id, otp, [("LPG_19KG", 2)], [])
    _t2, _m2, customer2, driver2 = await a_customer(env)
    others, slip2, otp2 = await visit(env, _t2, customer2, driver2, ("LPG_19KG", 2))
    await complete(env, others, slip2, otp2, [("LPG_19KG", 2)], [])

    assert (await stats(env, drivers))["totalCompletedDeliveries"] == 1


# --- Today, and everything before it ----------------------------------------------------------------


async def test_an_older_round_counts_in_the_total_but_not_in_today(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, old, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, old, otp, [("LPG_19KG", 2)], [])
    await happened_days_ago(env, old, 5)

    counted = await stats(env, drivers)
    assert counted["completedDeliveriesToday"] == 0
    assert counted["totalCompletedDeliveries"] == 1


async def test_yesterdays_round_closed_today_counts_today(env):
    """A driver who closes a leftover from yesterday did that work **today**.

    The count is taken from the day the delivery was scheduled for, so such a round lands on
    yesterday's figure - a day the driver can no longer see - and today reads as one short.
    """
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await scheduled_for(env, slip_id, 1)

    await complete(env, drivers, slip_id, otp, [("LPG_19KG", 2)], [])

    assert (await stats(env, drivers))["completedDeliveriesToday"] == 1


# --- The other two counters ---------------------------------------------------------------------------


async def test_the_empties_counter_follows_what_came_back(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    await complete(env, drivers, slip_id, otp, [("LPG_19KG", 2)], [("LPG_19KG", 2)])

    assert (await stats(env, drivers))["totalEmptiesCollectedToday"] == 2


async def test_nothing_collected_reads_as_nothing(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    await complete(env, drivers, slip_id, otp, [("LPG_19KG", 2)], [])

    counted = await stats(env, drivers)
    assert counted["cashCollectedToday"] == 0
    assert counted["totalEmptiesCollectedToday"] == 0
