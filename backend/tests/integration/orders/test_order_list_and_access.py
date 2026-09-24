"""Listing, detail, cancellation, and who is allowed to see what (spec §6.5, §6.6).

The access-control tests are the point of this file. Orders are the first thing both apps
read, and the rule is asymmetric: staff see their merchant's orders, a customer sees only
their own, and everything outside that is a 404 rather than a 403 so ids cannot be probed.
"""

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order
from tests.integration.orders.conftest import (
    CUSTOMER_ORDERS,
    ORDERS,
    basket,
    code_of,
    created_order,
    customer_token,
    make_customer,
    order_staff,
    post,
    site_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


# --- List (§6.5) -------------------------------------------------------------------------


async def test_orders_are_listed_newest_first(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    first = await created_order(env, token, customer.id, ("LPG_5KG", 1))
    second = await created_order(env, token, customer.id, ("LPG_19KG", 1))

    listed = (await env.get(ORDERS, token)).json()

    assert [order["id"] for order in listed][:2] == [second["id"], first["id"]]


async def test_the_list_is_a_plain_array(env):
    """Spec §1: the apps do not paginate in Phase 1."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id)

    body = (await env.get(ORDERS, token)).json()

    assert isinstance(body, list)
    assert body[0]["items"], "each row carries its lines, so the list needs no second call"


async def test_the_customer_filter_narrows_a_staff_list(env):
    token, merchant, _user = await order_staff(env)
    one = await make_customer(env, merchant)
    two = await make_customer(env, merchant)
    await created_order(env, token, one.id)
    await created_order(env, token, two.id)

    listed = (await env.get(f"{ORDERS}?customerId={one.id}", token)).json()

    assert len(listed) == 1
    assert listed[0]["customerId"] == one.id


async def test_status_active_means_every_non_terminal_status(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    live = await created_order(env, token, customer.id)
    done = await created_order(env, token, customer.id, ("LPG_5KG", 1))
    await env.execute(
        Order.__table__.update().where(Order.__table__.c.id == done["id"]).values(status="DELIVERED")
    )

    active = (await env.get(f"{ORDERS}?status=ACTIVE", token)).json()
    everything = (await env.get(f"{ORDERS}?status=ALL", token)).json()

    assert [order["id"] for order in active] == [live["id"]]
    assert len(everything) == 2


async def test_a_specific_status_filters_exactly(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id)

    placed = (await env.get(f"{ORDERS}?status=PLACED", token)).json()
    delivered = (await env.get(f"{ORDERS}?status=DELIVERED", token)).json()

    assert len(placed) == 1
    assert delivered == []


async def test_an_unknown_status_is_a_422_not_an_empty_list(env):
    """An empty list would read as "no orders in this state" and hide a client typo."""
    token, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}?status=SHIPPED", token)

    assert response.status_code == 422
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == "status"


async def test_search_matches_number_customer_and_summary(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id, ("LPG_19KG", 2))

    by_number = (await env.get(f"{ORDERS}?search={order['orderNumber']}", token)).json()
    by_customer = (await env.get(f"{ORDERS}?search=Sharma", token)).json()
    by_summary = (await env.get(f"{ORDERS}?search=19 KG", token)).json()

    assert [o["id"] for o in by_number] == [order["id"]]
    assert [o["id"] for o in by_customer] == [order["id"]]
    assert [o["id"] for o in by_summary] == [order["id"]]


async def test_the_list_is_scoped_to_the_acting_merchant(env):
    theirs, their_merchant, _u = await order_staff(env)
    their_customer = await make_customer(env, their_merchant)
    await created_order(env, theirs, their_customer.id)
    ours, _merchant, _user = await order_staff(env)

    listed = (await env.get(ORDERS, ours)).json()

    assert listed == []


# --- Detail (§6.6) -----------------------------------------------------------------------


async def test_an_order_reads_back_with_its_lines_and_history(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id, ("LPG_19KG", 2), ("LPG_5KG", 1))

    detail = (await env.get(f"{ORDERS}/{order['id']}", token)).json()

    assert detail["id"] == order["id"]
    assert len(detail["items"]) == 2
    assert detail["statusHistory"][0]["status"] == "PLACED"
    # The cut-off is the one frozen at placement, not re-evaluated on read.
    assert detail["cutoff"]["cutoffTime"] == "16:00"


async def test_another_merchants_order_is_not_found_rather_than_forbidden(env):
    theirs, their_merchant, _u = await order_staff(env)
    their_customer = await make_customer(env, their_merchant)
    their_order = await created_order(env, theirs, their_customer.id)
    ours, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}/{their_order['id']}", ours)

    assert response.status_code == 404
    assert code_of(response) == "ORDER_NOT_FOUND"


async def test_reading_needs_orders_view(env):
    token, _merchant, _user = await order_staff(env, permissions=("orders.create",))

    response = await env.get(ORDERS, token)

    assert response.status_code == 403


# --- The customer channel ------------------------------------------------------------------


async def test_a_customer_places_and_sees_their_own_order(env):
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)

    placed = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {"customerId": customer.id, "items": basket(("LPG_19KG", 1)), "orderMode": "NEW"},
    )

    assert placed.status_code == 201, placed.text
    order = placed.json()
    # Placed from the customer app, so no staff name is attached.
    assert order["source"] == "CUSTOMER_APP"
    assert order["createdBy"] is None
    listed = (await env.get(CUSTOMER_ORDERS, token)).json()
    assert [o["id"] for o in listed] == [order["id"]]
    assert staff


async def test_a_customer_sees_only_their_own_orders(env):
    staff, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant)
    someone_else = await make_customer(env, merchant)
    await created_order(env, staff, someone_else.id)
    my_order = await created_order(env, staff, mine.id)
    token = await customer_token(env, mine)

    listed = (await env.get(CUSTOMER_ORDERS, token)).json()

    assert [o["id"] for o in listed] == [my_order["id"]]


async def test_a_customer_cannot_read_someone_elses_order(env):
    staff, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant)
    someone_else = await make_customer(env, merchant)
    their_order = await created_order(env, staff, someone_else.id)
    token = await customer_token(env, mine)

    response = await env.get(f"{CUSTOMER_ORDERS}/{their_order['id']}", token)

    assert response.status_code == 404


async def test_a_customer_cannot_order_for_somebody_else(env):
    staff, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant)
    someone_else = await make_customer(env, merchant)
    token = await customer_token(env, mine)

    response = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {"customerId": someone_else.id, "items": basket(("LPG_19KG", 1)), "orderMode": "NEW"},
    )

    assert response.status_code == 404
    assert code_of(response) == "CUSTOMER_NOT_FOUND"
    assert staff


async def test_the_customer_filter_cannot_widen_a_customers_own_list(env):
    """Honouring it would let them ask about someone else and get an empty list back
    instead of the 404 a direct read gives."""
    staff, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant)
    someone_else = await make_customer(env, merchant)
    await created_order(env, staff, someone_else.id)
    my_order = await created_order(env, staff, mine.id)
    token = await customer_token(env, mine)

    listed = (await env.get(f"{CUSTOMER_ORDERS}?customerId={someone_else.id}", token)).json()

    assert [o["id"] for o in listed] == [my_order["id"]]


async def test_a_customer_needs_no_permission_to_order(env):
    """Spec §2.1: customers hold no permissions; ownership is the rule."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    token = await customer_token(env, customer)

    statuses = await env.get(f"{CUSTOMER_ORDERS}/statuses", token)

    assert statuses.status_code == 200
    assert staff


async def test_a_merchant_token_cannot_use_the_customer_route(env):
    staff, merchant, _user = await order_staff(env)
    await make_customer(env, merchant)

    response = await env.get(CUSTOMER_ORDERS, staff)

    assert response.status_code == 403
    assert code_of(response) == "CHANNEL_NOT_ALLOWED"


# --- Cancel ---------------------------------------------------------------------------------


async def test_a_placed_order_can_be_cancelled(env):
    token, merchant, user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    response = await post(env, f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Customer changed their mind"})

    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "CANCELLED"
    trail = cancelled["statusHistory"]
    assert [step["status"] for step in trail] == ["PLACED", "CANCELLED"]
    assert trail[1]["by"] == user.full_name
    assert trail[1]["note"] == "Customer changed their mind"


async def test_an_order_on_the_van_can_no_longer_be_cancelled(env):
    """Once it is OUT_FOR_DELIVERY it is a delivery failure, not a cancellation."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    await env.execute(
        Order.__table__.update()
        .where(Order.__table__.c.id == order["id"])
        .values(status="OUT_FOR_DELIVERY")
    )

    response = await post(env, f"{ORDERS}/{order['id']}/cancel", token)

    assert response.status_code == 409
    assert code_of(response) == "ORDER_NOT_CANCELLABLE"


async def test_a_cancelled_order_cannot_be_cancelled_twice(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    await post(env, f"{ORDERS}/{order['id']}/cancel", token)

    again = await post(env, f"{ORDERS}/{order['id']}/cancel", token)

    assert again.status_code == 409


async def test_cancelling_needs_orders_cancel(env):
    token, merchant, _user = await order_staff(env, permissions=("orders.view", "orders.create"))
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    response = await post(env, f"{ORDERS}/{order['id']}/cancel", token)

    assert response.status_code == 403


async def test_industrial_end_to_end_through_both_channels(env):
    """The whole flow: staff quote, customer places, both read the same order back."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)
    token = await customer_token(env, customer)

    quote = await post(
        env,
        f"{ORDERS}/quote",
        staff,
        {"customerId": customer.id, "items": basket(("LPG_47_5KG_L", 6), ("LPG_47_5KG_V", 2))},
    )
    placed = await post(
        env,
        CUSTOMER_ORDERS,
        token,
        {
            "customerId": customer.id,
            "items": basket(("LPG_47_5KG_L", 6), ("LPG_47_5KG_V", 2)),
            "orderMode": "NEW",
            "deliverySiteId": site,
        },
    )

    assert quote.status_code == 200, quote.text
    assert placed.status_code == 201, placed.text
    order = placed.json()
    # The quote and the order agree, because both priced through the same helper.
    assert order["totalAmount"] == quote.json()["totalAmount"]

    staff_view = (await env.get(f"{ORDERS}/{order['id']}", staff)).json()
    customer_view = (await env.get(f"{CUSTOMER_ORDERS}/{order['id']}", token)).json()
    assert staff_view["id"] == customer_view["id"] == order["id"]
    assert staff_view["totalAmount"] == customer_view["totalAmount"]

    stored = await env.scalar(select(Order).where(Order.id == order["id"]))
    assert stored.merchant_id == merchant.id
