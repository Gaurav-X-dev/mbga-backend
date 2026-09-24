"""Quoting and the cut-off catalogue (spec §6.1-6.3)."""

import pytest

from tests.integration.orders.conftest import (
    ORDERS,
    basket,
    code_of,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


# --- Status catalogue (§6.1) ----------------------------------------------------------------


async def test_the_status_catalogue_is_sorted_and_complete(env):
    token, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}/statuses", token)

    assert response.status_code == 200, response.text
    statuses = response.json()
    assert [s["code"] for s in statuses] == [
        "PLACED",
        "CONFIRMED",
        "PREPARING",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
        "CANCELLED",
    ]
    assert [s["sequence"] for s in statuses] == [1, 2, 3, 4, 5, 99]
    # The app renders its timeline from this, so every field it reads must be present.
    assert all({"code", "label", "sequence", "tone", "description", "isTerminal"} <= set(s) for s in statuses)
    assert [s["isTerminal"] for s in statuses] == [False, False, False, False, True, True]


# --- Cut-off (§6.2) --------------------------------------------------------------------------


async def test_the_cutoff_endpoint_answers_with_a_real_utc_instant(env):
    token, _merchant, _user = await order_staff(env)

    response = await env.get(f"{ORDERS}/cutoff", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cutoffTime"] == "16:00"
    assert isinstance(body["withinCutoff"], bool)
    # A `Z` instant, not a naive wall-clock string that JS would read as local time.
    assert body["scheduledDeliveryDate"].endswith("Z")
    assert body["message"]


# --- Quote (§6.3) ----------------------------------------------------------------------------


async def test_a_quote_prices_from_the_active_month_and_breaks_gst_out(env):
    """Spec §18.1: 1 × 19 KG @ ₹1,800 → total 1800, subtotal 1525, GST 275."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 1))}
    )

    assert response.status_code == 200, response.text
    quote = response.json()
    assert quote["totalAmount"] == 1800
    assert quote["subtotal"] == 1525
    assert quote["gstAmount"] == 275
    assert quote["gstPercent"] == 18
    # GST is broken out of the total, never added on top.
    assert quote["subtotal"] + quote["gstAmount"] == quote["totalAmount"]


async def test_a_quote_totals_several_lines(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    quote = (
        await post(
            env,
            f"{ORDERS}/quote",
            token,
            {"customerId": customer.id, "items": basket(("LPG_19KG", 2), ("LPG_5KG", 1))},
        )
    ).json()

    assert quote["totalCylinders"] == 3
    # 2 × 1800 + 1 × 490.
    assert quote["totalAmount"] == 4090
    assert {item["cylinderType"]: item["lineTotal"] for item in quote["items"]} == {
        "LPG_19KG": 3600,
        "LPG_5KG": 490,
    }
    assert quote["items"][0]["cylinderLabel"] in {"19 KG", "5 KG"}


async def test_amounts_are_whole_rupee_integers(env):
    """Spec §1: Money is an integer. A float would round differently in every client."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    quote = (
        await post(env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 1))})
    ).json()

    for key in ("totalAmount", "subtotal", "gstAmount"):
        assert isinstance(quote[key], int), key
    assert isinstance(quote["items"][0]["unitPrice"], int)


async def test_a_quote_carries_the_cutoff_so_the_screen_needs_one_call(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    quote = (
        await post(env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 1))})
    ).json()

    assert quote["cutoff"]["cutoffTime"] == "16:00"
    assert quote["cutoff"]["scheduledDeliveryDate"].endswith("Z")


async def test_a_customer_price_override_reaches_the_quote(env):
    """The point of resolving through one helper: an override set on the Price Setting tab
    changes what the customer is quoted, not just what that screen shows."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    override = await env.client.put(
        f"/api/v1/merchant/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700, "reason": "Loyalty discount"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert override.status_code == 200, override.text

    quote = (
        await post(env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 2))})
    ).json()

    assert quote["items"][0]["unitPrice"] == 1700
    assert quote["totalAmount"] == 3400


async def test_duplicate_lines_are_merged_in_the_quote(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    quote = (
        await post(
            env,
            f"{ORDERS}/quote",
            token,
            {"customerId": customer.id, "items": basket(("LPG_19KG", 2), ("LPG_19KG", 1))},
        )
    ).json()

    assert len(quote["items"]) == 1
    assert quote["items"][0]["quantity"] == 3


async def test_an_empty_basket_is_a_field_error(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await post(env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": []})

    assert response.status_code == 422
    assert code_of(response) == "VALIDATION_ERROR"
    assert response.json()["detail"]["fields"][0]["field"] == "items"


async def test_hippo_for_a_retail_customer_names_the_cylinder(env):
    token, merchant, _user = await order_staff(env)
    retail = await make_customer(env, merchant, customer_type="RETAIL")

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": retail.id, "items": basket(("LPG_422KG_HIPPO", 1))}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "LPG_422KG_HIPPO"


async def test_a_quantity_over_the_limit_names_the_cylinder(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 51))}
    )

    assert response.status_code == 422
    field = response.json()["detail"]["fields"][0]
    assert field["field"] == "LPG_19KG"
    assert field["message"] == "Enter 1–50"


async def test_an_unknown_customer_is_not_found(env):
    token, _merchant, _user = await order_staff(env)

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": "nope", "items": basket(("LPG_19KG", 1))}
    )

    assert response.status_code == 404
    assert code_of(response) == "CUSTOMER_NOT_FOUND"


async def test_another_merchants_customer_cannot_be_quoted(env):
    _theirs, their_merchant, _u = await order_staff(env)
    their_customer = await make_customer(env, their_merchant)
    ours, _merchant, _user = await order_staff(env)

    response = await post(
        env, f"{ORDERS}/quote", ours, {"customerId": their_customer.id, "items": basket(("LPG_19KG", 1))}
    )

    assert response.status_code == 404


async def test_a_quote_does_not_require_an_approved_customer(env):
    """A quote is a price, not a commitment - the Create Order screen shows it while the
    eligibility banner explains why the button is still disabled."""
    token, merchant, _user = await order_staff(env)
    pending = await make_customer(env, merchant, account_status="UNDER_REVIEW", kyc_status="PENDING")

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": pending.id, "items": basket(("LPG_19KG", 1))}
    )

    assert response.status_code == 200, response.text


async def test_quoting_needs_orders_create(env):
    token, merchant, _user = await order_staff(env, permissions=("orders.view",))
    customer = await make_customer(env, merchant)

    response = await post(
        env, f"{ORDERS}/quote", token, {"customerId": customer.id, "items": basket(("LPG_19KG", 1))}
    )

    assert response.status_code == 403
