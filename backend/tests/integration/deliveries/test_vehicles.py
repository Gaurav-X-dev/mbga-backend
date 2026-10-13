"""The merchant's van list, and what it changes about assigning one.

A vehicle used to be a string typed into the assignment form. Nothing held the list, so a typo
did not fail - it quietly created a second van, and the rule that stops one person being sent
out twice could not see that `MP09 GH 4521` and `MP09GH4521` were the same vehicle.

A van belongs to the merchant, not to a driver: whoever is on shift takes whatever is loaded.
These tests pin that, and the two clashes that are real - one person on two vans, and one van
with two people.
"""

import pytest
from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip
from app.modules.vehicles.models import Vehicle
from tests.integration.deliveries.conftest import (
    ORDERS,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    refill,
    settings_overrides,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

VEHICLES = "/api/v1/merchant/vehicles"
VAN = "MP09 GH 4521"


async def a_yard(env):
    """Staff, stock, a customer and two drivers - enough to clash them against each other."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 400)
    first = await make_driver(env, merchant)
    second = await make_driver(env, merchant)
    return token, merchant, customer, first, second


async def add_van(env, token, number=VAN, **extra):
    return await env.post(VEHICLES, token, {"number": number, **extra})


async def assign(env, token, customer, driver, *, van=VAN, date=None, quantity=2):
    order = await place_order(env, token, customer.id, ("LPG_19KG", quantity))
    delivery = {"vehicleNumber": van, "driverUserId": driver.id}
    if date is not None:
        delivery["deliveryDate"] = date.isoformat()
    return await env.post(f"{ORDERS}/{order['id']}/confirm", token, {"delivery": delivery})


# --- The list -------------------------------------------------------------------------------


async def test_a_van_can_be_added_from_the_panel(env):
    token, _merchant, _customer, _a, _b = await a_yard(env)

    response = await add_van(env, token, label="Tata 407")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["number"] == VAN
    assert body["label"] == "Tata 407"
    assert body["isActive"] is True
    # No capacity: the office does not know these figures, and a field nobody fills reads as
    # missing data on every screen.
    assert "capacity" not in body


async def test_the_plate_is_normalised_on_the_way_in(env):
    """So one van cannot be added twice under two spellings."""
    token, _merchant, _customer, _a, _b = await a_yard(env)

    response = await add_van(env, token, number="  mp09   gh 4521 ")

    assert response.status_code == 201, response.text
    assert response.json()["number"] == VAN


async def test_the_same_van_cannot_be_added_twice(env):
    token, _merchant, _customer, _a, _b = await a_yard(env)
    await add_van(env, token)

    again = await add_van(env, token, number="mp09gh 4521")

    assert again.status_code in {201, 409}, again.text
    # Normalisation collapses the spacing but not a missing space, so only the exact plate
    # clashes. What must never happen is two rows for the identical normalised number.
    duplicate = await add_van(env, token, number="MP09 GH 4521")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "VEHICLE_ALREADY_EXISTS"


async def test_a_van_is_retired_not_deleted(env):
    """Every slip it carried still names it, and those slips have to keep reading."""
    token, _merchant, _customer, _a, _b = await a_yard(env)
    vehicle_id = (await add_van(env, token)).json()["id"]

    retired = await env.client.patch(
        f"{VEHICLES}/{vehicle_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"isActive": False},
    )

    assert retired.status_code == 200, retired.text
    assert retired.json()["isActive"] is False
    listed = (await env.get(f"{VEHICLES}", token)).json()
    assert vehicle_id in {row["id"] for row in listed["items"]}


async def test_the_available_route_serves_the_live_ones(env):
    """The name the assignment screen asks for. It used to get a 405, because
    `/vehicles/{vehicleId}` matched `available` as an id."""
    token, _merchant, _customer, _a, _b = await a_yard(env)
    live = (await add_van(env, token)).json()["id"]
    retired = (await add_van(env, token, number="MP09 ZZ 0001")).json()["id"]
    await env.client.patch(
        f"{VEHICLES}/{retired}",
        headers={"Authorization": f"Bearer {token}"},
        json={"isActive": False},
    )

    offered = await env.get(f"{VEHICLES}/available", token)

    assert offered.status_code == 200, offered.text
    assert {row["id"] for row in offered.json()["items"]} == {live}


async def test_the_assignment_dropdown_asks_for_the_live_ones(env):
    token, _merchant, _customer, _a, _b = await a_yard(env)
    live = (await add_van(env, token)).json()["id"]
    retired = (await add_van(env, token, number="MP09 ZZ 0001")).json()["id"]
    await env.client.patch(
        f"{VEHICLES}/{retired}",
        headers={"Authorization": f"Bearer {token}"},
        json={"isActive": False},
    )

    offered = (await env.get(f"{VEHICLES}?activeOnly=true", token)).json()

    assert {row["id"] for row in offered["items"]} == {live}


async def test_another_merchants_van_is_not_found(env):
    _theirs_token, _m, _c, _a, _b = await a_yard(env)
    ours_token, _merchant, _customer, _a2, _b2 = await a_yard(env)
    theirs_token, _m2, _c2, _a3, _b3 = await a_yard(env)
    theirs = (await add_van(env, theirs_token)).json()["id"]

    response = await env.client.patch(
        f"{VEHICLES}/{theirs}",
        headers={"Authorization": f"Bearer {ours_token}"},
        json={"label": "Mine now"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VEHICLE_NOT_FOUND"


# --- Assigning one --------------------------------------------------------------------------


async def test_a_van_on_the_list_may_be_assigned(env):
    token, _merchant, customer, driver, _other = await a_yard(env)
    await add_van(env, token)

    response = await assign(env, token, customer, driver)

    assert response.status_code == 200, response.text


async def test_a_van_nobody_added_is_added_here(env):
    """Refusing it meant the office could not dispatch until somebody opened the vehicles
    screen - the wrong order, with the van in the yard and the order waiting."""
    token, merchant, customer, driver, _other = await a_yard(env)
    await add_van(env, token)

    response = await assign(env, token, customer, driver, van="MP09 ZZ 9999")

    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        added = await db.scalar(
            select(Vehicle).where(
                Vehicle.merchant_id == merchant.id, Vehicle.number == "MP09 ZZ 9999"
            )
        )
    assert added is not None
    assert added.is_active is True


async def test_the_typo_still_lands_on_one_row(env):
    """Normalisation is what actually stops the duplicates, not the refusal."""
    token, merchant, customer, driver, _other = await a_yard(env)

    await assign(env, token, customer, driver, van="mp09  zz 9999")
    await assign(env, token, customer, driver, van="MP09 ZZ 9999")

    async with env.sessions() as db:
        rows = list(
            await db.scalars(
                select(Vehicle).where(
                    Vehicle.merchant_id == merchant.id, Vehicle.number == "MP09 ZZ 9999"
                )
            )
        )
    assert len(rows) == 1


async def test_a_retired_van_is_refused(env):
    token, _merchant, customer, driver, _other = await a_yard(env)
    vehicle_id = (await add_van(env, token)).json()["id"]
    await env.client.patch(
        f"{VEHICLES}/{vehicle_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"isActive": False},
    )

    response = await assign(env, token, customer, driver)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"][0]["code"] == "vehicle_inactive"


async def test_a_merchant_with_no_vans_yet_is_let_through(env):
    """Otherwise the first assignment is impossible until somebody finds the vehicles screen."""
    token, _merchant, customer, driver, _other = await a_yard(env)

    response = await assign(env, token, customer, driver, van="MP09 NEW 0001")

    assert response.status_code == 200, response.text


async def test_the_spelling_used_to_assign_does_not_matter(env):
    """The list is the authority, so the slip records the plate as the list spells it."""
    token, _merchant, customer, driver, _other = await a_yard(env)
    await add_van(env, token)

    response = await assign(env, token, customer, driver, van="  mp09 gh   4521")

    assert response.status_code == 200, response.text
    slip = await env.scalar(
        select(DeliverySlip).where(DeliverySlip.id == response.json()["deliverySlipId"])
    )
    assert slip.vehicle_number == VAN


# --- The two clashes that are real ------------------------------------------------------------


async def test_a_driver_keeps_taking_orders_on_the_same_van(env):
    """A round is filled through the morning. This is the ordinary case, not a clash."""
    token, _merchant, customer, driver, _other = await a_yard(env)
    await add_van(env, token)

    first = await assign(env, token, customer, driver)
    second = await assign(env, token, customer, driver)
    third = await assign(env, token, customer, driver)

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 200]


async def test_one_person_on_two_vans_in_a_day_is_refused(env):
    token, _merchant, customer, driver, _other = await a_yard(env)
    await add_van(env, token)
    await add_van(env, token, number="MP09 ZZ 0002")
    await assign(env, token, customer, driver)

    elsewhere = await assign(env, token, customer, driver, van="MP09 ZZ 0002")

    assert elsewhere.status_code == 422, elsewhere.text
    assert elsewhere.json()["detail"]["fields"][0]["code"] == "driver_already_assigned"


async def test_one_van_with_two_people_in_a_day_is_refused(env):
    """The same mistake from the van's side, and it was not checked at all."""
    token, _merchant, customer, driver, other = await a_yard(env)
    await add_van(env, token)
    await assign(env, token, customer, driver)

    response = await assign(env, token, customer, other)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"][0]["code"] == "vehicle_already_assigned"


async def test_the_same_van_goes_to_someone_else_tomorrow(env):
    """A van is not a driver's. Whoever is on shift takes whatever is loaded."""
    from datetime import timedelta

    from app.shared.date_time.business_calendar import business_today

    token, _merchant, customer, driver, other = await a_yard(env)
    await add_van(env, token)
    await assign(env, token, customer, driver)

    tomorrow = await assign(
        env, token, customer, other, date=business_today() + timedelta(days=1)
    )

    assert tomorrow.status_code == 200, tomorrow.text


async def test_a_settled_round_frees_the_van(env):
    token, _merchant, customer, driver, other = await a_yard(env)
    await add_van(env, token)
    first = await assign(env, token, customer, driver)
    await env.execute(
        update(DeliverySlip)
        .where(DeliverySlip.id == first.json()["deliverySlipId"])
        .values(status="DELIVERED")
    )

    response = await assign(env, token, customer, other)

    assert response.status_code == 200, response.text


async def test_a_van_is_only_added_once_however_often_it_is_used(env):
    """Auto-registration must not grow a row per assignment."""
    token, merchant, customer, driver, _other = await a_yard(env)

    await assign(env, token, customer, driver, van="MP09 OLD 0001")
    await assign(env, token, customer, driver, van="MP09 OLD 0001")

    async with env.sessions() as db:
        rows = list(
            await db.scalars(
                select(Vehicle).where(
                    Vehicle.merchant_id == merchant.id, Vehicle.number == "MP09 OLD 0001"
                )
            )
        )
    assert len(rows) == 1
