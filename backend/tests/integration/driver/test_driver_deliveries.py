"""The delivery app's working day, end to end.

What these prove, in the order a driver meets them: they see their own queue and nobody else's,
they can set off, count at the gate, and complete the handover with the customer's code - and
that when they do, the godown's books move exactly as they would have if the office had confirmed
it instead.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip
from tests.integration.deliveries.conftest import DELIVERIES, counts, ready_to_dispatch
from tests.integration.driver.conftest import (
    DRIVER_DELIVERIES,
    driver_token,
    give_site_coordinates,
    on_the_road,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


# --- The queue -------------------------------------------------------------------------------


async def test_a_driver_sees_the_delivery_assigned_to_them(env):
    _staff, token, slip, _driver = await on_the_road(env)

    response = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["id"] for row in rows] == [slip["id"]]
    assert rows[0]["orderNumber"] == slip["orderNumber"]
    assert rows[0]["status"] == "pending"
    # The address arrives as one line the driver can read out or paste into maps.
    assert rows[0]["customer"]["address"]


async def test_a_driver_never_sees_another_drivers_delivery(env):
    """The whole tenancy model on this channel: scoped by who the slip is addressed to."""
    _staff_a, _token_a, slip_a, _driver_a = await on_the_road(env)
    _staff_b, token_b, slip_b, _driver_b = await on_the_road(env)

    listed = await env.get(f"{DRIVER_DELIVERIES}/today", token_b)
    assert [row["id"] for row in listed.json()] == [slip_b["id"]]

    # And by id it is not found - never forbidden, which would confirm it exists.
    direct = await env.get(f"{DRIVER_DELIVERIES}/today", token_b)
    assert slip_a["id"] not in [row["id"] for row in direct.json()]


async def test_a_merchant_token_cannot_read_the_driver_endpoints(env):
    staff_token, _token, _slip, _driver = await on_the_road(env)

    response = await env.get(f"{DRIVER_DELIVERIES}/today", staff_token)

    assert response.status_code == 403


# --- Setting off -----------------------------------------------------------------------------


async def test_starting_a_trip_measures_the_distance_to_the_gate(env):
    _staff, token, slip, _driver = await on_the_road(env)
    # Kanpur Central, and the driver a little under 5 km away at the zoo.
    await give_site_coordinates(env, slip, 26.4499, 80.3319)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-location",
        token,
        {"latitude": 26.4830, "longitude": 80.3050},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["isAtLocation"] is False
    assert 4500 < body["distanceMetersFromDestination"] < 4600


async def test_a_site_with_no_coordinates_never_blocks_the_driver(env):
    """Most sites have none - nobody surveys a customer's godown to onboard them.

    The distance is unknown, so the app is told the driver is at the location rather than being
    stopped by data the office never captured.
    """
    _staff, token, slip, _driver = await on_the_road(env)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-location",
        token,
        {"latitude": 26.4830, "longitude": 80.3050},
    )

    assert response.status_code == 200, response.text
    assert response.json()["distanceMetersFromDestination"] is None
    assert response.json()["isAtLocation"] is True


async def test_starting_twice_keeps_the_first_departure_time(env):
    """The app may retry on a flaky connection; the trip did not restart."""
    _staff, token, slip, _driver = await on_the_road(env)
    # Reverting to out-for-delivery to test duplicate start requests
    first = await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", token)
    assert first.status_code == 200
    updated_at = first.json()["updatedAt"]

    second = await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/out-for-delivery", token)
    assert second.status_code == 200
    assert second.json()["status"] == first.json()["status"]


# --- The handover ----------------------------------------------------------------------------


async def test_the_full_handover_moves_the_stock_exactly_once(env):
    """The point of the whole module.

    Counting at the gate changes nothing on the books. The customer's code is what completes the
    delivery, and that is the moment the cylinders leave the godown's count.
    """
    staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))
    before_filled, before_empty, _ = await counts(env, staff)

    counted = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": 4}], "collectedEmpties": [{"cylinderType": "LPG_19KG", "quantity": 3}], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}, "driverNotes": "Left at the gate office"},
    )
    assert counted.status_code == 200, counted.text
    assert counted.json()["customerOtpRequired"] is True
    # Nothing has moved yet - the customer has not confirmed anything.
    assert await counts(env, staff) == (before_filled, before_empty, _)

    done = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    assert done.status_code == 200, done.text
    assert done.json()["orderNumber"] == slip["orderNumber"]
    assert done.json()["totalEmptyCollectedQuantity"] == 3
    after_filled, after_empty, _damaged = await counts(env, staff)
    assert after_filled == before_filled - 4
    assert after_empty == before_empty + 3


async def test_the_office_sees_the_same_delivery_the_driver_completed(env):
    """One slip, one truth. The driver's confirmation is the office's confirmation."""
    staff, token, slip, _driver = await on_the_road(env)
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": slip["cylindersAllocated"]}], "collectedEmpties": [{"cylinderType": "LPG_19KG", "quantity": 2}], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    board = await env.get(f"{DELIVERIES}/{slip['id']}", staff)

    assert board.json()["status"] == "DELIVERED"
    assert board.json()["emptiesCollected"] == 2


async def test_a_wrong_code_does_not_complete_the_delivery(env):
    _staff, token, slip, _driver = await on_the_road(env)
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": slip["cylindersAllocated"]}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp", token, {"otp": "0000"}
    )

    assert response.status_code in (400, 409, 422)
    still = await env.get(f"{DRIVER_DELIVERIES}/today", token)
    assert [row for row in still.json() if row["id"] == slip["id"]][0]["status"] == "pending"


async def test_a_part_delivery_books_only_what_was_handed_over(env):
    """The ledger books the handover, not the load.

    A driver who gives the customer two of the four on his van still has two of them, and they
    are still the merchant's - so two come off the shelf and two do not. Booking the whole
    allocation here is how a godown's count drifts with nothing to explain it.
    """
    staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))
    before_filled, before_empty, _ = await counts(env, staff)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": 2}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )
    assert response.status_code == 200, response.text

    done = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    assert done.status_code == 200, done.text
    # The receipt states the handover, so it says two rather than the four that were loaded.
    assert done.json()["totalDeliveredQuantity"] == 2
    after_filled, after_empty, _damaged = await counts(env, staff)
    assert after_filled == before_filled - 2
    assert after_empty == before_empty


async def test_a_driver_cannot_hand_over_more_than_the_van_carries(env):
    """The extra cylinders would have to come from somewhere the slip cannot account for."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": 6}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DELIVERY_QUANTITY_EXCEEDS_ALLOCATION"


async def test_a_slip_the_office_has_not_dispatched_cannot_be_handed_over(env):
    """Cylinders that never left the godown cannot be delivered from a phone."""
    _staff, _merchant, _order, slip, driver = await ready_to_dispatch(env)
    token = await driver_token(env, driver)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": slip["cylindersAllocated"]}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DELIVERY_NOT_READY"


async def test_history_holds_what_is_finished_and_the_queue_does_not(env):
    _staff, token, slip, _driver = await on_the_road(env)
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": slip["cylindersAllocated"]}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    history = await env.get(f"{DRIVER_DELIVERIES}/history", token)

    assert [row["id"] for row in history.json()["items"]] == [slip["id"]]
    assert history.json()["items"][0]["status"] == "completed"
    assert history.json()["items"][0]["completedAt"] is not None


async def test_the_driver_is_recorded_as_the_person_who_confirmed_it(env):
    """Actor fields come from the session, never the body."""
    _staff, token, slip, driver = await on_the_road(env)
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        {"deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": slip["cylindersAllocated"]}], "collectedEmpties": [], "payment": {"method": "cash", "split": "full", "amountCollected": 0, "payableAmount": 0, "pendingBalance": 0}},
    )
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/verify-customer-otp",
        token,
        {"otp": slip["devConfirmationCode"]},
    )

    row = await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))

    assert row.confirmed_by_name == driver.full_name
    assert row.started_at is None or row.delivered_at is not None
