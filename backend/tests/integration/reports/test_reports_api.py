from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from tests.integration.deliveries.conftest import ready_to_dispatch
from tests.integration.orders.conftest import customer_token

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

REPORTS = "/api/v1/merchant/reports"
MERCHANT_AUTH = "/api/v1/merchant/auth"
ADMIN_REPORTS = "/api/v1/admin/reports"
ADMIN_AUTH = "/api/v1/admin/auth"


async def report_token(env, merchant, *permissions):
    role = f"reports_{uuid4().hex[:8]}"
    await env.create_role(role, "MERCHANT", list(permissions or ("reports.view", "reports.export")))
    user, _ = await env.create_merchant_staff(merchant, roles=(role,))
    login = await env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def super_admin_token(env):
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def test_daily_delivery_report_is_tenant_scoped_and_has_drilldown(env):
    _staff, merchant, _order, slip, _driver = await ready_to_dispatch(env)
    await ready_to_dispatch(env)  # another merchant's slip must never leak
    token = await report_token(env, merchant)

    response = await env.get(f"{REPORTS}?type=DAILY_DELIVERY", token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "DAILY_DELIVERY"
    assert [row["id"] for row in body["rows"]] == [slip["id"]]
    assert body["rows"][0]["displayId"] == slip["slipNumber"]
    assert body["rows"][0]["_details"]["fields"]
    assert "Customer ID" not in {
        field["label"] for field in body["rows"][0]["_details"]["fields"]
    }
    assert body["metadata"]["currency"] == "INR"
    assert body["metadata"]["timezone"] == "Asia/Kolkata"
    assert body["period"]["from"].endswith("+05:30")


async def test_report_permissions_and_login_channel_are_enforced(env):
    _staff, merchant, _order, slip, _driver = await ready_to_dispatch(env)
    no_permission_role = f"no_reports_{uuid4().hex[:8]}"
    # A role with no permission at all is rejected at login as unassigned. Give it an unrelated
    # merchant permission so the report endpoint, rather than authentication, makes the denial.
    await env.create_role(no_permission_role, "MERCHANT", ["tasks.view"])
    user, _ = await env.create_merchant_staff(merchant, roles=(no_permission_role,))
    merchant_login = await env.sign_in(MERCHANT_AUTH, user.mobile_number)

    denied = await env.get(f"{REPORTS}?type=DAILY_DELIVERY", merchant_login["token"]["access_token"])
    assert denied.status_code == 403

    customer = await env.scalar(
        select(CustomerProfile).where(CustomerProfile.id == slip["customerId"])
    )
    customer_access = await customer_token(env, customer)
    wrong_channel = await env.get(f"{REPORTS}?type=DAILY_DELIVERY", customer_access)
    assert wrong_channel.status_code == 403


async def test_financial_and_payment_reports_require_domain_permissions(env):
    _staff, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    token = await report_token(env, merchant, "reports.view", "reports.export")

    expense = await env.get(f"{REPORTS}?type=EXPENSE", token)
    payment = await env.get(f"{REPORTS}?type=PAYMENT_COLLECTION", token)

    assert expense.status_code == 403
    assert payment.status_code == 403


async def test_csv_export_has_download_security_headers(env):
    _staff, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    token = await report_token(env, merchant)

    response = await env.get(f"{REPORTS}/export?type=DAILY_DELIVERY&format=CSV", token)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"


async def test_every_report_type_returns_its_contract(env):
    _staff, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    token = await report_token(
        env,
        merchant,
        "reports.view",
        "reports.export",
        "expenses.view",
        "payments.reconcile",
    )

    for report_type in (
        "DAILY_DELIVERY",
        "PAYMENT_COLLECTION",
        "PENDING_PICKUP",
        "EXPENSE",
        "STOCK_MOVEMENT",
        "PROFIT_LOSS",
        "TAX_GST",
    ):
        response = await env.get(f"{REPORTS}?type={report_type}", token)
        assert response.status_code == 200, f"{report_type}: {response.text}"
        body = response.json()
        assert body["type"] == report_type
        assert isinstance(body["summary"], list)
        assert isinstance(body["columns"], list)
        assert isinstance(body["rows"], list)


async def test_super_admin_can_view_all_merchants_and_filter_one(env):
    _staff_a, merchant_a, _order_a, slip_a, _driver_a = await ready_to_dispatch(env)
    _staff_b, merchant_b, _order_b, slip_b, _driver_b = await ready_to_dispatch(env)
    token = await super_admin_token(env)

    global_response = await env.get(f"{ADMIN_REPORTS}?type=DAILY_DELIVERY", token)
    selected_response = await env.get(
        f"{ADMIN_REPORTS}?type=DAILY_DELIVERY&merchantId={merchant_a.id}", token
    )

    assert global_response.status_code == 200, global_response.text
    global_body = global_response.json()
    assert global_body["metadata"]["scope"] == "ALL_MERCHANTS"
    global_rows = {row["id"]: row for row in global_body["rows"]}
    assert {slip_a["id"], slip_b["id"]}.issubset(global_rows)
    assert global_rows[slip_a["id"]]["merchantId"] == merchant_a.id
    assert global_rows[slip_b["id"]]["merchantId"] == merchant_b.id
    assert global_body["columns"][0]["key"] == "merchant"

    assert selected_response.status_code == 200, selected_response.text
    selected_body = selected_response.json()
    assert selected_body["metadata"]["scope"] == "MERCHANT"
    assert selected_body["metadata"]["merchantId"] == merchant_a.id
    assert [row["id"] for row in selected_body["rows"]] == [slip_a["id"]]


async def test_admin_and_merchant_report_channels_stay_isolated(env):
    _staff, merchant, _order, _slip, _driver = await ready_to_dispatch(env)
    admin_token = await super_admin_token(env)
    merchant_token = await report_token(env, merchant)

    admin_on_merchant_api = await env.get(f"{REPORTS}?type=DAILY_DELIVERY", admin_token)
    merchant_on_admin_api = await env.get(
        f"{ADMIN_REPORTS}?type=DAILY_DELIVERY", merchant_token
    )

    assert admin_on_merchant_api.status_code == 403
    assert merchant_on_admin_api.status_code == 403
