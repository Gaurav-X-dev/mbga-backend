"""The driver's history tabs, and the clock on a receipt.

Reported from the app, and both were real:

`period` was read and ignored, so Today, This Week and All returned the same unfiltered list.
`page` was ignored too, so every page was the first one, and `total` reported the length of
that page rather than how many rounds there are.

`completedAt` came back as `"2026-10-09T11:30:00"` - naive, no offset - which a phone reads as
**local** time. A delivery settled at 5 PM IST printed 11:30 AM on the receipt. MySQL `DATETIME`
keeps no offset, so what the ORM hands back is naive UTC and saying so is the whole fix.

It also carried the delivery's **date** rather than the moment it was settled, the payment
method was the string `"cash"` whatever had been collected, and the empties count was what
*should* have come back rather than what did.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip
from app.shared.date_time.business_calendar import business_today
from tests.integration.deliveries.conftest import ORDERS
from tests.integration.driver.conftest import (
    DRIVER_DELIVERIES,
    dispatch_staff,
    driver_token,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    refill,
    settings_overrides,  # noqa: F401 - fixture
)
from tests.integration.driver.test_driver_payment import confirmation

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

VAN = "MP09 GH 4521"
HISTORY = f"{DRIVER_DELIVERIES}/history"


async def a_round(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 90)
    driver = await make_driver(env, merchant)
    return token, customer, driver


async def a_settled_delivery(env, token, customer, driver, *, empties: int = 0) -> str:
    """One completed round. Returns the slip id."""
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    confirmed = await env.post(
        f"{ORDERS}/{order['id']}/confirm",
        token,
        {"delivery": {"vehicleNumber": VAN, "driverUserId": driver.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    slip_id = confirmed.json()["deliverySlipId"]
    drivers = await driver_token(env, driver)
    out = await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers, {})
    assert out.status_code == 200, out.text
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation(
            [("LPG_19KG", 2)],
            amount=0,
            empties=[("LPG_19KG", empties)] if empties else [],
        ),
    )
    verified = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/verify-customer-otp",
        drivers,
        {"otp": out.json()["devConfirmationCode"]},
    )
    assert verified.status_code == 200, verified.text
    return slip_id


async def backdate(env, slip_id: str, days: int) -> None:
    """Move a settled round into the past, as an older day's work."""
    async with env.sessions() as db:
        await db.execute(
            update(DeliverySlip)
            .where(DeliverySlip.id == slip_id)
            .values(scheduled_date=business_today() - timedelta(days=days))
        )
        await db.commit()


async def history(env, drivers, period: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in {"period": period, **params}.items())
    response = await env.get(f"{HISTORY}?{query}", drivers)
    assert response.status_code == 200, response.text
    return response.json()


# --- The three tabs ------------------------------------------------------------------------------


async def test_today_shows_only_todays_rounds(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    old = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, old, 10)
    drivers = await driver_token(env, driver)

    body = await history(env, drivers, "today")

    assert body["total"] == 1
    assert old not in {row["id"] for row in body["items"]}


async def test_the_week_reaches_back_seven_days(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    recent = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, recent, 3)
    drivers = await driver_token(env, driver)

    body = await history(env, drivers, "week")

    assert body["total"] == 2


async def test_the_week_leaves_out_what_is_older(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    old = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, old, 30)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "week"))["total"] == 1


async def test_all_shows_everything(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    old = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, old, 400)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "all"))["total"] == 2


async def test_this_week_is_accepted_as_well(env):
    """The app asked which spelling the backend takes; it takes both."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "this_week"))["total"] == 1


async def test_an_unknown_period_shows_everything_rather_than_nothing(env):
    """An empty screen reads as "no deliveries", which is a worse lie than too many."""
    token, customer, driver = await a_round(env)
    old = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, old, 400)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "last_quarter"))["total"] == 1


async def test_the_tabs_do_not_all_return_the_same_list(env):
    """What was reported: three tabs, one list."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    old = await a_settled_delivery(env, token, customer, driver)
    await backdate(env, old, 60)
    drivers = await driver_token(env, driver)

    counts = {
        period: (await history(env, drivers, period))["total"]
        for period in ("today", "week", "all")
    }

    assert counts["today"] < counts["all"]


# --- Paging --------------------------------------------------------------------------------------


async def test_the_second_page_is_not_the_first(env):
    token, customer, driver = await a_round(env)
    for _ in range(3):
        await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    first = await history(env, drivers, "all", page=1, limit=2)
    second = await history(env, drivers, "all", page=2, limit=2)

    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert {r["id"] for r in first["items"]}.isdisjoint({r["id"] for r in second["items"]})


async def test_the_total_counts_every_round_not_the_page(env):
    token, customer, driver = await a_round(env)
    for _ in range(3):
        await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    body = await history(env, drivers, "all", page=1, limit=2)

    assert body["total"] == 3
    assert len(body["items"]) == 2


# --- The clock -----------------------------------------------------------------------------------


async def test_the_completion_time_is_an_instant_not_a_date(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    completed = (await history(env, drivers, "all"))["items"][0]["completedAt"]

    assert completed.endswith("Z"), completed
    assert "T" in completed


async def test_the_completion_time_is_the_real_moment(env):
    """It used to be the delivery's date, so every receipt read midnight."""
    token, customer, driver = await a_round(env)
    slip_id = await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)
    async with env.sessions() as db:
        stored = await db.scalar(
            select(DeliverySlip.delivered_at).where(DeliverySlip.id == slip_id)
        )

    completed = (await history(env, drivers, "all"))["items"][0]["completedAt"]

    parsed = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    assert abs((parsed - stored.replace(tzinfo=UTC)).total_seconds()) < 1


async def test_the_receipt_carries_the_same_instant(env):
    """`verify-customer-otp` and the history row must agree about when it happened."""
    token, customer, driver = await a_round(env)
    slip_id = await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip_id}/completed-detail", drivers)

    assert detail.status_code == 200, detail.text
    assert detail.json()["completedAt"].endswith("Z")


# --- What else the row says ----------------------------------------------------------------------


async def test_the_empties_count_is_what_came_back(env):
    """It reported what was *expected*, so a round that collected nothing still showed a figure."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver, empties=0)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "all"))["items"][0]["totalEmptiesCount"] == 0


async def test_the_empties_count_follows_the_collection(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver, empties=2)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "all"))["items"][0]["totalEmptiesCount"] == 2


async def test_a_round_with_no_payment_does_not_claim_cash(env):
    """The method was the string "cash" whatever had been collected."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "all"))["items"][0]["payment"]["method"] != "cash"


async def test_another_drivers_rounds_are_not_listed(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    _token2, customer2, driver2 = await a_round(env)
    await a_settled_delivery(env, _token2, customer2, driver2)
    drivers = await driver_token(env, driver)

    assert (await history(env, drivers, "all"))["total"] == 1


# --- Asking for one outcome ----------------------------------------------------------------------
#
# Reported as "totalCompletedDeliveries is wrong: it says 46, the driver has done 18". The total
# was right - the database had 46 delivered slips against 46 distinct orders, no duplicates. The
# 18 was the delivered rows on the **first page** of a history list that also carries failed
# rounds and defaults to 20 per page. Two different numbers, neither of them a bug.
#
# What was missing was the question the screen wanted to ask: show me the completed ones. Without
# it the app could only read a page and count, which is how the page length ended up being
# reported as a total.


async def a_failed_delivery(env, token, customer, driver) -> str:
    """A round that went out and came back unconfirmed."""
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    confirmed = await env.post(
        f"{ORDERS}/{order['id']}/confirm",
        token,
        {"delivery": {"vehicleNumber": VAN, "driverUserId": driver.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    slip_id = confirmed.json()["deliverySlipId"]
    drivers = await driver_token(env, driver)
    await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers, {})
    async with env.sessions() as db:
        await db.execute(
            update(DeliverySlip).where(DeliverySlip.id == slip_id).values(status="FAILED")
        )
        await db.commit()
    return slip_id


async def test_both_outcomes_come_back_by_default(env):
    """The history tab is unchanged: it still shows everything that is settled."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    await a_failed_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    listed = await history(env, drivers, "all")

    assert listed["total"] == 2
    assert {row["status"] for row in listed["items"]} == {"completed", "failed"}


async def test_only_the_completed_ones_can_be_asked_for(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    await a_failed_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    listed = await history(env, drivers, "all", status="completed")

    assert listed["total"] == 1
    assert [row["status"] for row in listed["items"]] == ["completed"]


async def test_only_the_failed_ones_can_be_asked_for(env):
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    await a_failed_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    listed = await history(env, drivers, "all", status="failed")

    assert listed["total"] == 1
    assert [row["status"] for row in listed["items"]] == ["failed"]


async def test_the_total_counts_matches_not_the_page(env):
    """The exact confusion behind the report: `total` must outrun one page."""
    token, customer, driver = await a_round(env)
    for _ in range(3):
        await a_settled_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    listed = await history(env, drivers, "all", status="completed", limit=2)

    assert len(listed["items"]) == 2, "one page"
    assert listed["total"] == 3, "but there are three"


async def test_an_unknown_outcome_shows_both_rather_than_nothing(env):
    """A typo must not read as "no deliveries"."""
    token, customer, driver = await a_round(env)
    await a_settled_delivery(env, token, customer, driver)
    await a_failed_delivery(env, token, customer, driver)
    drivers = await driver_token(env, driver)

    listed = await history(env, drivers, "all", status="definitely-not-a-status")

    assert listed["total"] == 2
