"""The driver's own tally of the day, size by size.

The godown asks two questions when a van comes back: how many cylinders went out, and how many
shells came in. The driver had no screen that answered either per size. `GET /driver/inventory`
answers a different question - what is on the van right now - and its per-size empty count was
hard-coded to zero, so a van carrying shells reported none of them against any size while the
total printed beside them was right.
"""

import pytest

from tests.integration.deliveries.conftest import ORDERS
from tests.integration.driver.conftest import (
    DRIVER,
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


async def a_round(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    for cylinder in ("LPG_5KG", "LPG_19KG"):
        await refill(env, token, cylinder, 60)
    driver = await make_driver(env, merchant)
    return token, customer, driver


async def dispatch(env, token, customer, driver, *lines):
    order = await place_order(env, token, customer.id, *lines)
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
    return drivers, slip_id, out.json()["devConfirmationCode"]


async def hand_over(env, drivers, slip_id, otp, delivered, empties):
    confirmed = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation(delivered, amount=0, empties=empties),
    )
    assert confirmed.status_code == 200, confirmed.text
    verified = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/verify-customer-otp", drivers, {"otp": otp}
    )
    assert verified.status_code == 200, verified.text


async def summary(env, drivers) -> dict:
    response = await env.get(f"{DRIVER}/day-summary", drivers)
    assert response.status_code == 200, response.text
    return response.json()


def lines_of(body) -> dict[str, dict]:
    return {line["cylinderType"]: line for line in body["byType"]}


# --- The two questions the godown asks -----------------------------------------------------------


async def test_the_day_starts_empty(env):
    token, customer, driver = await a_round(env)
    drivers, _slip, _otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))

    body = await summary(env, drivers)

    assert (body["totalDelivered"], body["totalEmptiesCollected"]) == (0, 0)
    assert body["byType"] == []


async def test_a_completed_handover_is_counted(env):
    token, customer, driver = await a_round(env)
    drivers, slip, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))

    await hand_over(env, drivers, slip, otp, [("LPG_19KG", 2)], [("LPG_19KG", 1)])

    body = await summary(env, drivers)
    assert body["totalDelivered"] == 2
    assert body["totalEmptiesCollected"] == 1
    assert body["deliveriesCompleted"] == 1


async def test_each_size_is_counted_on_its_own(env):
    token, customer, driver = await a_round(env)
    drivers, slip, otp = await dispatch(
        env, token, customer, driver, ("LPG_19KG", 2), ("LPG_5KG", 3)
    )

    await hand_over(
        env, drivers, slip, otp, [("LPG_19KG", 2), ("LPG_5KG", 3)], [("LPG_5KG", 2)]
    )

    lines = lines_of(await summary(env, drivers))
    assert (lines["LPG_19KG"]["delivered"], lines["LPG_19KG"]["emptiesCollected"]) == (2, 0)
    assert (lines["LPG_5KG"]["delivered"], lines["LPG_5KG"]["emptiesCollected"]) == (3, 2)


async def test_the_totals_are_the_lines_added_up(env):
    """The screen prints both; they have to agree or the driver is handing in two figures."""
    token, customer, driver = await a_round(env)
    drivers, slip, otp = await dispatch(
        env, token, customer, driver, ("LPG_19KG", 2), ("LPG_5KG", 3)
    )
    await hand_over(
        env, drivers, slip, otp, [("LPG_19KG", 2), ("LPG_5KG", 3)], [("LPG_5KG", 2)]
    )

    body = await summary(env, drivers)

    assert body["totalDelivered"] == sum(line["delivered"] for line in body["byType"])
    assert body["totalEmptiesCollected"] == sum(
        line["emptiesCollected"] for line in body["byType"]
    )


async def test_several_rounds_add_up(env):
    token, customer, driver = await a_round(env)
    drivers, first, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))
    await hand_over(env, drivers, first, otp, [("LPG_19KG", 2)], [("LPG_19KG", 2)])
    _d, second, otp2 = await dispatch(env, token, customer, driver, ("LPG_19KG", 1))

    await hand_over(env, drivers, second, otp2, [("LPG_19KG", 1)], [])

    body = await summary(env, drivers)
    assert body["totalDelivered"] == 3
    assert body["deliveriesCompleted"] == 2


async def test_a_part_delivery_counts_what_was_handed_over(env):
    """Not what the van set out with - the godown matches against cylinders, not slips."""
    token, customer, driver = await a_round(env)
    drivers, slip, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 3))

    await hand_over(env, drivers, slip, otp, [("LPG_19KG", 1)], [])

    assert (await summary(env, drivers))["totalDelivered"] == 1


async def test_a_shell_from_an_earlier_visit_counts_today(env):
    """It came back today, whichever visit it was owed from."""
    token, customer, driver = await a_round(env)
    drivers, first, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))
    await hand_over(env, drivers, first, otp, [("LPG_19KG", 2)], [])
    _d, second, otp2 = await dispatch(env, token, customer, driver, ("LPG_5KG", 1))

    await hand_over(env, drivers, second, otp2, [("LPG_5KG", 1)], [("LPG_19KG", 2)])

    lines = lines_of(await summary(env, drivers))
    assert lines["LPG_19KG"]["emptiesCollected"] == 2


# --- What it leaves out -----------------------------------------------------------------------


async def test_a_delivery_still_on_the_van_is_not_counted(env):
    token, customer, driver = await a_round(env)
    drivers, first, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))
    await hand_over(env, drivers, first, otp, [("LPG_19KG", 2)], [])

    await dispatch(env, token, customer, driver, ("LPG_19KG", 5))

    assert (await summary(env, drivers))["totalDelivered"] == 2


async def test_another_drivers_round_is_not_counted(env):
    token, customer, driver = await a_round(env)
    drivers, slip, otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))
    await hand_over(env, drivers, slip, otp, [("LPG_19KG", 2)], [])
    _token2, customer2, driver2 = await a_round(env)
    others, slip2, otp2 = await dispatch(env, _token2, customer2, driver2, ("LPG_19KG", 4))
    await hand_over(env, others, slip2, otp2, [("LPG_19KG", 4)], [])

    assert (await summary(env, drivers))["totalDelivered"] == 2


async def test_the_date_is_the_business_day(env):
    from app.shared.date_time.business_calendar import business_today

    token, customer, driver = await a_round(env)
    drivers, _slip, _otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))

    assert (await summary(env, drivers))["date"] == business_today().isoformat()


# --- The van's own count, which was partly a mock -------------------------------------------------


async def test_the_van_reports_empties_against_each_size(env):
    """`emptyCount` was hard-coded to zero on every line of `GET /driver/inventory`."""
    token, customer, driver = await a_round(env)
    drivers, slip, _otp = await dispatch(env, token, customer, driver, ("LPG_19KG", 2))
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip}/confirm",
        drivers,
        confirmation([("LPG_19KG", 2)], amount=0, empties=[("LPG_19KG", 2)]),
    )

    response = await env.get(f"{DRIVER}/inventory", drivers)

    assert response.status_code == 200, response.text
    line = next(r for r in response.json()["stockByType"] if r["cylinderType"] == "LPG_19KG")
    assert line["emptyCount"] == 2
