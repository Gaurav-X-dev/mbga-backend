"""The dispatch board's list, and who may touch it (spec §10.1, §2.1).

The list is a work queue, so its ordering is behaviour rather than decoration: a merchant with
forty slips on screen has to see what is on the road and what still has to load without scrolling
past a week of completed deliveries.

The access tests are written as the negative, because a slip carries a customer's address and
mobile and a driver's name - one merchant's board leaking into another's is a data breach, not a
cosmetic bug.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    VIEW_ONLY,
    code_of,
    dispatch_staff,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    ready_to_dispatch,
    refill,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def board(env, token: str, **params) -> list[dict]:
    response = await env.get(DELIVERIES, token, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


async def scene(env):
    """Staff with stock, a priced month and a customer - ready to raise several slips."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, quantity=94)
    return token, merchant, customer


async def raise_slip(env, token: str, customer_id: str, *, driver: str = "Arjun Singh", quantity: int = 2) -> dict:
    order = await place_order(env, token, customer_id, ("LPG_19KG", quantity))
    created = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": driver},
    )
    assert created.status_code == 201, created.text
    return created.json()


# --- Ordering ---------------------------------------------------------------------------------


async def test_the_board_is_a_work_queue_not_a_log(env):
    """Spec §10.1: DISPATCHED -> SCHEDULED -> FAILED -> DELIVERED.

    What is on the road first, then what has to go out, then what went wrong. Delivered slips are
    last because they need nobody.
    """
    token, _merchant, customer = await scene(env)
    delivered = await raise_slip(env, token, customer.id)
    dispatched = await raise_slip(env, token, customer.id)
    scheduled = await raise_slip(env, token, customer.id)
    failed = await raise_slip(env, token, customer.id)

    await env.post(f"{DELIVERIES}/{delivered['id']}/dispatch", token)
    code = (await env.get(f"{DELIVERIES}/{delivered['id']}", token)).json()
    assert code  # the slip is readable between the two calls
    dispatch_response = await env.post(f"{DELIVERIES}/{dispatched['id']}/dispatch", token)
    assert dispatch_response.status_code == 200
    # Confirm the first with the mock code, which this deployment accepts.
    confirmed = await env.post(
        f"{DELIVERIES}/{delivered['id']}/confirm", token, {"otp": "4321", "emptiesCollected": 0}
    )
    assert confirmed.status_code == 200, confirmed.text
    await env.post(f"{DELIVERIES}/{failed['id']}/fail", token, {"reason": "Shop closed"})

    statuses = [slip["status"] for slip in await board(env, token)]

    assert statuses == ["DISPATCHED", "SCHEDULED", "FAILED", "DELIVERED"]
    assert scheduled


async def test_the_order_is_stable_between_refreshes(env):
    """Same-day slips share a scheduled date, so the tie-break has to be deterministic.

    MySQL DATETIME keeps whole seconds; without the slip-number tie-break the board would
    reshuffle every time somebody pulled to refresh.
    """
    token, _merchant, customer = await scene(env)
    for _ in range(4):
        await raise_slip(env, token, customer.id)

    first = [slip["slipNumber"] for slip in await board(env, token)]
    second = [slip["slipNumber"] for slip in await board(env, token)]

    assert first == second
    assert first == sorted(first, reverse=True), "newest slip number first within a status"


# --- Filters -----------------------------------------------------------------------------------


async def test_the_board_filters_by_status(env):
    token, _merchant, customer = await scene(env)
    going_out = await raise_slip(env, token, customer.id)
    await raise_slip(env, token, customer.id)
    await env.post(f"{DELIVERIES}/{going_out['id']}/dispatch", token)

    dispatched = await board(env, token, status="DISPATCHED")
    scheduled = await board(env, token, status="SCHEDULED")
    everything = await board(env, token, status="ALL")

    assert [slip["id"] for slip in dispatched] == [going_out["id"]]
    assert len(scheduled) == 1
    assert len(everything) == 2


async def test_an_unknown_status_returns_nothing_rather_than_an_error(env):
    """A stale chip on a screen shows an empty list, not a dialog."""
    token, _merchant, customer = await scene(env)
    await raise_slip(env, token, customer.id)

    assert await board(env, token, status="ON_FIRE") == []


async def test_the_board_searches_the_things_staff_actually_have(env):
    """Spec §10.1: slip id, order number, customer name, vehicle number."""
    token, _merchant, customer = await scene(env)
    slip = await raise_slip(env, token, customer.id, driver="Arjun Singh")

    by_slip = await board(env, token, search=slip["slipNumber"])
    by_order = await board(env, token, search=slip["orderNumber"])
    by_customer = await board(env, token, search="Sharma")
    by_vehicle = await board(env, token, search="MP09")
    by_driver = await board(env, token, search="Arjun")
    by_mobile = await board(env, token, search=customer.mobile_number[-6:])

    for found in (by_slip, by_order, by_customer, by_vehicle, by_driver, by_mobile):
        assert [row["id"] for row in found] == [slip["id"]]


async def test_a_search_that_matches_nothing_is_empty(env):
    token, _merchant, customer = await scene(env)
    await raise_slip(env, token, customer.id)

    assert await board(env, token, search="MH12 XX 9999") == []


# --- Tenancy ------------------------------------------------------------------------------------


async def test_one_merchants_board_is_invisible_to_another(env):
    """A slip carries a customer's address and mobile. This is a breach, not a cosmetic bug."""
    mine_token, _mine, mine_customer = await scene(env)
    theirs_token, _theirs, theirs_customer = await scene(env)
    theirs = await raise_slip(env, theirs_token, theirs_customer.id)
    await raise_slip(env, mine_token, mine_customer.id)

    mine_board = await board(env, mine_token)

    assert theirs["id"] not in [slip["id"] for slip in mine_board]
    assert len(mine_board) == 1


async def test_another_merchants_slip_is_a_404_not_a_403(env):
    """Slip numbers are sequential and guessable, so a 403 would confirm the slip exists."""
    _mine_token, _mine, _c = await scene(env)
    theirs_token, _theirs, theirs_customer = await scene(env)
    theirs = await raise_slip(env, theirs_token, theirs_customer.id)
    mine_token, _merchant, my_customer = await scene(env)
    await raise_slip(env, mine_token, my_customer.id)

    response = await env.get(f"{DELIVERIES}/{theirs['id']}", mine_token)

    assert response.status_code == 404
    assert code_of(response) == "DELIVERY_NOT_FOUND"


async def test_another_merchants_slip_cannot_be_dispatched(env):
    """The tenancy check runs before the state check, so this is a 404 and not a 409."""
    theirs_token, _theirs, theirs_customer = await scene(env)
    theirs = await raise_slip(env, theirs_token, theirs_customer.id)
    mine_token, _mine, _c = await scene(env)

    response = await env.post(f"{DELIVERIES}/{theirs['id']}/dispatch", mine_token)

    assert response.status_code == 404
    # And their slip is untouched.
    assert (await env.get(f"{DELIVERIES}/{theirs['id']}", theirs_token)).json()["status"] == "SCHEDULED"


async def test_a_slip_is_written_against_the_calling_merchant(env):
    token, merchant, customer = await scene(env)
    slip = await raise_slip(env, token, customer.id)

    owner = await env.scalar(select(DeliverySlip.merchant_id).where(DeliverySlip.id == slip["id"]))

    assert owner == merchant.id


async def test_an_order_from_another_merchant_cannot_be_slipped(env):
    """The order id is checked against the caller's merchant, not taken on trust."""
    theirs_token, _theirs, theirs_customer = await scene(env)
    theirs_order = await place_order(env, theirs_token, theirs_customer.id, ("LPG_19KG", 2))
    mine_token, _mine, _c = await scene(env)

    response = await env.post(
        DELIVERIES,
        mine_token,
        {"orderId": theirs_order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"},
    )

    assert response.status_code == 404
    assert code_of(response) == "ORDER_NOT_FOUND"


async def test_another_merchants_driver_cannot_be_assigned(env):
    """Otherwise a slip sends a job to somebody else's employee."""
    _theirs_token, theirs_merchant, _c = await scene(env)
    theirs_driver = await make_driver(env, theirs_merchant)
    mine_token, _mine, my_customer = await scene(env)
    order = await place_order(env, mine_token, my_customer.id, ("LPG_19KG", 2))

    response = await env.post(
        DELIVERIES,
        mine_token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverUserId": theirs_driver.id},
    )

    assert response.status_code == 404
    assert code_of(response) == "DELIVERY_USER_NOT_FOUND"


# --- Permissions --------------------------------------------------------------------------------


async def test_reading_the_board_needs_delivery_view(env):
    token, _merchant, _user = await dispatch_staff(env, permissions=("orders.view",))

    response = await env.get(DELIVERIES, token)

    assert response.status_code == 403
    assert code_of(response) == "PERMISSION_DENIED"


async def test_dispatching_needs_delivery_confirm(env):
    """Reading the board and sending a van out are separate rights (spec §2.1)."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, quantity=60)
    slip = await raise_slip(env, token, customer.id)
    viewer_token, _same, _user2 = await dispatch_staff(env, merchant, permissions=VIEW_ONLY)

    readable = await env.get(f"{DELIVERIES}/{slip['id']}", viewer_token)
    dispatched = await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", viewer_token)

    assert readable.status_code == 200
    assert dispatched.status_code == 403
    assert code_of(dispatched) == "PERMISSION_DENIED"


async def test_confirming_needs_delivery_confirm(env):
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, quantity=60)
    slip = await raise_slip(env, token, customer.id)
    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token)
    viewer_token, _same, _user2 = await dispatch_staff(env, merchant, permissions=VIEW_ONLY)

    response = await env.post(
        f"{DELIVERIES}/{slip['id']}/confirm", viewer_token, {"otp": "4321", "emptiesCollected": 0}
    )

    assert response.status_code == 403


async def test_the_board_needs_a_session(env):
    assert (await env.get(DELIVERIES)).status_code == 401


async def test_a_customer_token_cannot_reach_the_board(env):
    """There is no customer-facing dispatch board: a slip names the crew and the vehicle."""
    from tests.integration.notifications.conftest import customer as signed_in_customer
    from tests.integration.notifications.conftest import staff

    _staff_token, merchant, _u = await staff(env)
    customer_token, _profile, _cu = await signed_in_customer(env, merchant)

    mismatch = await env.get(DELIVERIES, customer_token)
    missing = await env.get("/api/v1/customer/deliveries", customer_token)

    assert mismatch.status_code == 403
    assert code_of(mismatch) == "CHANNEL_NOT_ALLOWED"
    assert missing.status_code == 404


# --- What may be slipped -------------------------------------------------------------------------


async def test_an_unconfirmed_order_cannot_have_a_van_loaded(env):
    """Loading cylinders for an order nobody reviewed is how a van goes out for a cancellation."""
    token, merchant, customer = await scene(env)
    from app.modules.orders.constants import OrderStatus
    from tests.integration.deliveries.conftest import set_order_status

    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    await set_order_status(env, order["id"], OrderStatus.PLACED)

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"},
    )

    assert response.status_code == 409
    assert code_of(response) == "ORDER_NOT_DISPATCHABLE"
    assert merchant


async def test_a_cancelled_order_cannot_have_a_van_loaded(env):
    token, _merchant, customer = await scene(env)
    from app.modules.orders.constants import OrderStatus
    from tests.integration.deliveries.conftest import set_order_status

    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    await set_order_status(env, order["id"], OrderStatus.CANCELLED)

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"},
    )

    assert response.status_code == 409


async def test_one_order_cannot_be_on_two_live_slips(env):
    """Two vans loading the same order is two dispatches and double the stock out."""
    token, _merchant, customer = await scene(env)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    body = {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"}
    first = await env.post(DELIVERIES, token, body)

    second = await env.post(DELIVERIES, token, body)

    assert first.status_code == 201
    assert second.status_code == 409
    assert code_of(second) == "DELIVERY_ALREADY_EXISTS"
    assert first.json()["slipNumber"] in second.json()["detail"]["message"]


async def test_a_failed_slip_frees_the_order_for_a_new_one(env):
    """Which is how a failed delivery gets rescheduled."""
    token, _merchant, customer = await scene(env)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))
    body = {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun"}
    first = await env.post(DELIVERIES, token, body)
    await env.post(f"{DELIVERIES}/{first.json()['id']}/fail", token, {"reason": "Shop closed"})

    second = await env.post(DELIVERIES, token, body)

    assert second.status_code == 201
    assert second.json()["slipNumber"] != first.json()["slipNumber"]


# --- Crew and vehicle ----------------------------------------------------------------------------


async def test_a_slip_must_name_a_driver(env):
    token, _merchant, customer = await scene(env)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))

    response = await env.post(DELIVERIES, token, {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521"})

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "driverName"


async def test_a_blocked_driver_cannot_be_assigned(env):
    """They cannot open the app, so the job would sit unseen while the office believed otherwise."""
    token, merchant, customer = await scene(env)
    blocked = await make_driver(env, merchant, status="BLOCKED")
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverUserId": blocked.id},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "driverUserId"


async def test_an_unapproved_driver_cannot_be_assigned(env):
    token, merchant, customer = await scene(env)
    pending = await make_driver(env, merchant, approval="PENDING")
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverUserId": pending.id},
    )

    assert response.status_code == 422


async def test_the_slip_names_the_driver_from_their_account(env):
    """Not an employee code: this string goes into the customer's notification."""
    _token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    assert slip["driverName"] == "Test Driver"


async def test_the_vehicle_number_is_normalised(env):
    """Read off a plate, so case and spacing are noise."""
    token, _merchant, customer = await scene(env)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))

    response = await env.post(
        DELIVERIES,
        token,
        {"orderId": order["id"], "vehicleNumber": " mp09  gh 4521 ", "driverName": "Arjun"},
    )

    assert response.status_code == 201
    assert response.json()["vehicleNumber"] == "MP09 GH 4521"


async def test_an_unusable_confirmation_method_is_refused(env):
    """A slip no screen can confirm would need a database edit to get out of."""
    token, _merchant, customer = await scene(env)
    order = await place_order(env, token, customer.id, ("LPG_19KG", 2))

    response = await env.post(
        DELIVERIES,
        token,
        {
            "orderId": order["id"],
            "vehicleNumber": "MP09 GH 4521",
            "driverName": "Arjun",
            "confirmationMethod": "SIGNATURE",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "confirmationMethod"
