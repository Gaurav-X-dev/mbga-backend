"""Repeat order: the one-tap path, and everything that can have changed since.

The risk in a repeat is not that it fails - it is that it quietly succeeds with the wrong
basket or the wrong price. These tests are mostly about that: prices re-read from today's
card, a suspended customer refused, a dropped cylinder reported rather than skipped, a dead
delivery site asked about rather than swapped for the registered address.
"""

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
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

PRICING = "/api/v1/merchant/pricing"


async def _add_site(env, customer_id: str, name: str) -> str:
    """Give a customer another delivery site, and return its id."""
    from datetime import UTC, datetime
    from uuid import uuid4

    site_id = str(uuid4())
    async with env.sessions() as db:
        db.add(
            CustomerDeliverySite(
                id=site_id,
                customer_id=customer_id,
                name=name,
                address_line1="Plot 9",
                address_city="Indore",
                address_state="Madhya Pradesh",
                address_pincode="452020",
                is_primary=False,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return site_id


async def _move_price(env, token, cylinder_type: str, base: int, markup: int):
    months = (await env.get(f"{PRICING}/months", token)).json()
    response = await env.client.put(
        f"{PRICING}/months/{months[0]['id']}/entries",
        json={"cylinderType": cylinder_type, "bpclBaseRate": base, "tierMarkup": markup},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


# --- Preview: the Repeat Order screen opening -------------------------------------------------


async def test_the_preview_fills_the_sheet_from_the_last_order(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    previous = await created_order(env, token, customer.id, ("LPG_19KG", 2), ("LPG_5KG", 1))

    preview = await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["sourceOrderId"] == previous["id"]
    assert body["sourceOrderNumber"] == previous["orderNumber"]
    assert body["sourceOrderStatus"] == "PLACED"
    assert body["sourceItemsSummary"] == previous["itemsSummary"]
    assert body["canReorder"] is True
    assert body["blockedReason"] is None
    # The basket comes back filled in - the app needs no second call.
    assert {item["cylinderType"]: item["quantity"] for item in body["items"]} == {
        "LPG_19KG": 2,
        "LPG_5KG": 1,
    }
    assert body["totalAmount"] == previous["totalAmount"]
    assert body["previousTotalAmount"] == previous["totalAmount"]
    assert body["priceChanged"] is False


async def test_the_preview_reports_a_price_that_has_moved(env):
    """The confirm sheet has to be able to say "more than last time" before placing."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    previous = await created_order(env, token, customer.id, ("LPG_19KG", 2))
    await _move_price(env, token, "LPG_19KG", 1900, 200)

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["previousTotalAmount"] == previous["totalAmount"] == 3600
    assert body["totalAmount"] == 4200
    assert body["priceChanged"] is True
    assert body["canReorder"] is True


async def test_the_last_order_is_the_most_recent_one(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id, ("LPG_5KG", 1))
    newest = await created_order(env, token, customer.id, ("LPG_19KG", 3))

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["sourceOrderId"] == newest["id"]
    assert body["items"][0]["quantity"] == 3


async def test_a_cancelled_order_is_skipped_in_favour_of_the_last_one_that_stood(env):
    """"The same as last time" means the last order that actually stood."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    stood = await created_order(env, token, customer.id, ("LPG_19KG", 2))
    cancelled = await created_order(env, token, customer.id, ("LPG_5KG", 1))
    await post(env, f"{ORDERS}/{cancelled['id']}/cancel", token)

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["sourceOrderId"] == stood["id"]


async def test_when_every_order_was_cancelled_the_newest_is_still_offered(env):
    """A customer who cancelled and wants to try again has not "never ordered"."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    only = await created_order(env, token, customer.id, ("LPG_19KG", 2))
    await post(env, f"{ORDERS}/{only['id']}/cancel", token)

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["sourceOrderId"] == only["id"]
    assert body["sourceOrderStatus"] == "CANCELLED"
    assert body["canReorder"] is True


async def test_a_customer_with_no_history_gets_a_clear_404(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)

    assert response.status_code == 404
    assert code_of(response) == "NO_PREVIOUS_ORDER"


async def test_the_preview_explains_rather_than_refusing_an_ineligible_customer(env):
    """The sheet needs to show the reason, not receive a 403 it has to translate."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id)
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(status="SUSPENDED")
    )

    response = await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["canReorder"] is False
    assert "suspended" in body["blockedReason"].lower()


async def test_staff_must_name_a_customer(env):
    token, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}/repeat", token)

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "customerId"


# --- Placing the repeat -------------------------------------------------------------------


async def test_a_repeat_places_the_same_basket_as_a_repeat_order(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    previous = await created_order(env, token, customer.id, ("LPG_19KG", 2), ("LPG_5KG", 1))

    response = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert response.status_code == 201, response.text
    repeat = response.json()
    assert repeat["orderMode"] == "REPEAT"
    assert repeat["id"] != previous["id"]
    assert {item["cylinderType"]: item["quantity"] for item in repeat["items"]} == {
        "LPG_19KG": 2,
        "LPG_5KG": 1,
    }
    assert repeat["status"] == "PLACED"


async def test_a_repeat_is_priced_today_not_copied_from_the_old_order(env):
    """The single most important rule: repeating must never resell at last month's rate."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    previous = await created_order(env, token, customer.id, ("LPG_19KG", 2))
    await _move_price(env, token, "LPG_19KG", 1900, 200)

    repeat = (await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})).json()

    assert previous["items"][0]["unitPrice"] == 1800
    assert repeat["items"][0]["unitPrice"] == 2100
    assert repeat["totalAmount"] == 4200
    # And the original is untouched.
    original = (await env.get(f"{ORDERS}/{previous['id']}", token)).json()
    assert original["totalAmount"] == 3600


async def test_a_repeat_picks_up_a_customer_price_override(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id, ("LPG_19KG", 2))
    await env.client.put(
        f"/api/v1/merchant/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700},
        headers={"Authorization": f"Bearer {token}"},
    )

    repeat = (await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})).json()

    assert repeat["items"][0]["unitPrice"] == 1700


async def test_a_repeat_is_refused_for_a_customer_who_may_no_longer_order(env):
    """A repeat is not a shortcut past eligibility."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id)
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(kyc_status="REJECTED")
    )

    response = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert response.status_code == 403


async def test_a_repeat_gets_its_own_order_number(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    previous = await created_order(env, token, customer.id)

    repeat = (await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})).json()

    assert repeat["orderNumber"] != previous["orderNumber"]
    assert int(repeat["orderNumber"][-4:]) == int(previous["orderNumber"][-4:]) + 1


async def test_repeating_twice_with_one_key_places_one_order(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id)

    first = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id}, **{"Idempotency-Key": "rep-1"})
    second = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id}, **{"Idempotency-Key": "rep-1"})

    assert first.json()["id"] == second.json()["id"]
    rows = list(await env.execute(select(Order.id).where(Order.customer_id == customer.id)))
    assert len(rows) == 2, "the original plus one repeat"


# --- What can have changed since ------------------------------------------------------------


async def test_a_cylinder_that_left_the_price_card_blocks_the_preview(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, token, customer.id, ("LPG_5KG", 1))
    from app.modules.pricing.models import PricingEntry

    months = (await env.get(f"{PRICING}/months", token)).json()
    await env.execute(
        PricingEntry.__table__.delete().where(
            PricingEntry.__table__.c.pricing_month_id == months[0]["id"],
            PricingEntry.__table__.c.cylinder_type == "LPG_5KG",
        )
    )

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["canReorder"] is False
    assert "no price" in body["blockedReason"].lower()


async def test_hippo_becomes_unavailable_when_the_customer_is_no_longer_industrial(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)
    await created_order(env, token, customer.id, ("LPG_422KG_HIPPO", 1), deliverySiteId=site)
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(customer_type="RETAIL")
    )

    body = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()

    assert body["canReorder"] is False
    assert [row["cylinderType"] for row in body["unavailable"]] == ["LPG_422KG_HIPPO"]
    assert "industrial" in body["unavailable"][0]["reason"].lower()


async def test_a_dropped_line_is_a_409_not_a_silent_skip(env):
    """Receiving fewer cylinders than last time without being told is worse than a refusal."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)
    await created_order(env, token, customer.id, ("LPG_422KG_HIPPO", 1), deliverySiteId=site)
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(customer_type="RETAIL")
    )

    response = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert response.status_code == 409
    assert code_of(response) == "REORDER_NOT_POSSIBLE"


async def test_the_adjusted_basket_is_the_escape_hatch(env):
    """When the preview reports a line that cannot be repeated, the app sends the fix."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)
    await created_order(
        env, token, customer.id, ("LPG_422KG_HIPPO", 1), ("LPG_19KG", 2), deliverySiteId=site
    )
    await env.execute(
        CustomerProfile.__table__.update()
        .where(CustomerProfile.__table__.c.id == customer.id)
        .values(customer_type="RETAIL")
    )

    response = await post(
        env, f"{ORDERS}/repeat", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 2))}
    )

    assert response.status_code == 201, response.text
    assert [item["cylinderType"] for item in response.json()["items"]] == ["LPG_19KG"]


async def test_a_deactivated_delivery_site_is_asked_about_not_swapped(env):
    """Silently delivering to the registered address instead would be the wrong address."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)
    await created_order(env, token, customer.id, deliverySiteId=site)
    await env.execute(
        CustomerDeliverySite.__table__.update()
        .where(CustomerDeliverySite.__table__.c.id == site)
        .values(is_active=False)
    )

    preview = (await env.get(f"{ORDERS}/repeat?customerId={customer.id}", token)).json()
    placed = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert preview["canReorder"] is False
    assert "delivery site" in preview["blockedReason"].lower()
    # 403, not 422: with no active site at all this customer cannot order anything, which
    # eligibility decides before any field is looked at - the same answer a fresh order gives.
    assert placed.status_code == 403
    assert "delivery site" in placed.json()["detail"]["message"].lower()


async def test_a_dead_site_names_the_field_when_another_site_exists(env):
    """Eligibility passes (they have a live site), so the refusal is about *which* site."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    used_site = await site_of(env, customer.id)
    await created_order(env, token, customer.id, deliverySiteId=used_site)
    await _add_site(env, customer.id, "Plant B")
    await env.execute(
        CustomerDeliverySite.__table__.update()
        .where(CustomerDeliverySite.__table__.c.id == used_site)
        .values(is_active=False)
    )

    placed = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert placed.status_code == 422, placed.text
    assert placed.json()["detail"]["fields"][0]["field"] == "deliverySiteId"


async def test_a_new_site_can_be_chosen_for_the_repeat(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    old_site = await site_of(env, customer.id)
    await created_order(env, token, customer.id, deliverySiteId=old_site)

    new_id = await _add_site(env, customer.id, "Plant B")

    repeat = (
        await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id, "deliverySiteId": new_id})
    ).json()

    assert repeat["deliverySiteId"] == new_id
    assert repeat["deliverySiteName"] == "Plant B"


# --- Both channels ---------------------------------------------------------------------------


async def test_a_customer_repeats_without_naming_themselves(env):
    """Their session already says who they are."""
    staff, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await created_order(env, staff, customer.id, ("LPG_19KG", 2))
    token = await customer_token(env, customer)

    preview = await env.get(f"{CUSTOMER_ORDERS}/repeat", token)
    placed = await post(env, f"{CUSTOMER_ORDERS}/repeat", token)

    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["quantity"] == 2
    assert placed.status_code == 201, placed.text
    assert placed.json()["orderMode"] == "REPEAT"
    # Placed from their own app, so no staff name is attached.
    assert placed.json()["source"] == "CUSTOMER_APP"
    assert placed.json()["createdBy"] is None


async def test_a_customer_cannot_repeat_somebody_elses_last_order(env):
    staff, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant)
    someone_else = await make_customer(env, merchant)
    await created_order(env, staff, someone_else.id)
    await created_order(env, staff, mine.id, ("LPG_5KG", 1))
    token = await customer_token(env, mine)

    response = await env.get(f"{CUSTOMER_ORDERS}/repeat?customerId={someone_else.id}", token)

    # Checked against the session, not trusted - and refused rather than quietly swapped
    # for their own, which would hide a client bug. Same answer the create path gives.
    assert response.status_code == 404
    assert code_of(response) == "CUSTOMER_NOT_FOUND"
    # Omitting it works, because the session already says who they are.
    mine_preview = (await env.get(f"{CUSTOMER_ORDERS}/repeat", token)).json()
    assert mine_preview["items"][0]["cylinderType"] == "LPG_5KG"


async def test_staff_repeat_for_another_merchants_customer_is_not_found(env):
    theirs, their_merchant, _u = await order_staff(env)
    their_customer = await make_customer(env, their_merchant)
    await created_order(env, theirs, their_customer.id)
    ours, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}/repeat?customerId={their_customer.id}", ours)

    assert response.status_code == 404


async def test_repeating_needs_orders_create(env):
    token, merchant, _user = await order_staff(env, permissions=("orders.view",))
    customer = await make_customer(env, merchant)

    response = await post(env, f"{ORDERS}/repeat", token, {"customerId": customer.id})

    assert response.status_code == 403


# --- Repeat one specific order (order history) -------------------------------------------------


async def test_a_specific_order_can_be_repeated_by_id(env):
    """The "repeat this one" action in order history, rather than "the last one"."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    older = await created_order(env, token, customer.id, ("LPG_5KG", 4))
    await created_order(env, token, customer.id, ("LPG_19KG", 1))

    preview = (await env.get(f"{ORDERS}/{older['id']}/reorder", token)).json()
    placed = await post(env, f"{ORDERS}/{older['id']}/reorder", token)

    assert preview["sourceOrderId"] == older["id"]
    assert placed.status_code == 201, placed.text
    assert placed.json()["items"][0]["quantity"] == 4
    assert placed.json()["orderMode"] == "REPEAT"


async def test_repeating_another_merchants_order_by_id_is_not_found(env):
    theirs, their_merchant, _u = await order_staff(env)
    their_customer = await make_customer(env, their_merchant)
    their_order = await created_order(env, theirs, their_customer.id)
    ours, _merchant, _user = await order_staff(env)

    response = await post(env, f"{ORDERS}/{their_order['id']}/reorder", ours)

    assert response.status_code == 404
