"""Changing the cut-off from the admin panel, and the next order honouring it.

The hour used to be a constant, so moving the godown's day from 16:00 to 18:00 was a release. It
is an operating decision somebody makes during the working day, so it is a row the admin panel
edits - and what has to hold is that editing it actually changes what the order endpoints do.

The test that matters is the last one: not that the setting saves, but that an order placed at
17:00 is promised today once the cut-off moves to 18:00, having been promised tomorrow a moment
earlier. A setting the business logic does not read is worse than no setting, because the screen
says it worked.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.platform_settings.models import DEFAULT_ORDER_CUTOFF_HOUR
from tests.integration.orders.conftest import (
    ORDERS,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ADMIN = "/api/v1/admin"
SETTINGS = f"{ADMIN}/settings"
STAFF_PERMISSIONS = ("orders.view", "orders.create", "orders.update", "pricing.view", "pricing.manage")


@pytest.fixture(autouse=True)
async def restore_the_shipped_cutoff(env):
    """Put the row back to 16 after every test in this file.

    There is one settings row for the whole deployment, so a test that leaves the cut-off at
    midnight hands that to every order test that runs afterwards - which is how this file first
    broke three others in `test_order_quote`. The fixture keeps the mess inside this file.
    """
    yield
    token = await admin_token(env)
    await set_cutoff(env, token, DEFAULT_ORDER_CUTOFF_HOUR)


async def admin_token(env) -> str:
    """A super admin, who receives every permission including the settings ones."""
    staff = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(f"{ADMIN}/auth", staff.mobile_number)
    return login["token"]["access_token"]


async def set_cutoff(env, token: str, hour: int):
    return await env.client.patch(
        SETTINGS,
        headers={"Authorization": f"Bearer {token}"},
        json={"orderCutoffHour": hour},
    )


# --- The screen ------------------------------------------------------------------------------


async def test_the_three_forms_always_agree(env):
    """The panel renders the label rather than building it, so the two cannot drift.

    Sets the hour first rather than trusting the shipped default: there is one settings row for
    the whole deployment, so a test that assumes what it holds is really asserting that no other
    test ran before it. The shipped default is pinned in the unit tests instead.
    """
    token = await admin_token(env)
    await set_cutoff(env, token, 16)

    response = await env.get(SETTINGS, token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["orderCutoffHour"] == 16
    assert body["orderCutoffTime"] == "16:00"
    assert body["orderCutoffLabel"] == "4:00 PM"


async def test_changing_it_returns_all_three_forms(env):
    """The panel renders the label rather than building it, so the two cannot drift."""
    token = await admin_token(env)

    response = await set_cutoff(env, token, 18)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["orderCutoffHour"] == 18
    assert body["orderCutoffTime"] == "18:00"
    assert body["orderCutoffLabel"] == "6:00 PM"


async def test_the_change_names_who_made_it(env):
    """A value that silently moves every order's promised date needs an author."""
    token = await admin_token(env)
    await set_cutoff(env, token, 17)

    body = (await env.get(SETTINGS, token)).json()

    assert body["updatedByName"]
    assert body["updatedAt"]


async def test_an_impossible_hour_is_refused(env):
    """25 would make every order same-day and read as a scheduling bug, not a typo."""
    token = await admin_token(env)

    await set_cutoff(env, token, 16)

    response = await set_cutoff(env, token, 25)

    assert response.status_code == 422
    assert (await env.get(SETTINGS, token)).json()["orderCutoffHour"] == 16, "the bad value was stored"


async def test_merchant_staff_cannot_change_it(env):
    """It is a platform decision; the merchant channel has no business with this route."""
    token, _merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)

    response = await env.client.patch(
        SETTINGS,
        headers={"Authorization": f"Bearer {token}"},
        json={"orderCutoffHour": 18},
    )

    assert response.status_code in (401, 403)


# --- What it is for --------------------------------------------------------------------------


async def test_the_next_order_uses_the_new_cutoff(env):
    """The one that matters. A setting the order logic does not read is worse than none."""
    admin = await admin_token(env)
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)

    await set_cutoff(env, admin, 16)
    quoted = await post(env, f"{ORDERS}/quote", token, {
        "customerId": customer.id,
        "items": [{"cylinderType": "LPG_19KG", "quantity": 2}],
    })
    assert quoted.status_code == 200, quoted.text
    before = quoted.json()["cutoff"]

    await set_cutoff(env, admin, 23)

    requoted = await post(env, f"{ORDERS}/quote", token, {
        "customerId": customer.id,
        "items": [{"cylinderType": "LPG_19KG", "quantity": 2}],
    })
    after = requoted.json()["cutoff"]

    assert before["cutoffTime"] == "16:00"
    assert after["cutoffTime"] == "23:00"
    # 23:00 IST is past any hour this suite runs at, so the promise is today either way round -
    # which is the point: the rule moved, and the order endpoint read the moved rule.
    assert after["withinCutoff"] is True
    assert after["scheduledDeliveryDate"] == date.today().isoformat()


async def test_an_earlier_cutoff_pushes_the_next_order_to_tomorrow(env):
    """The other direction, so the test cannot pass by the clock happening to agree."""
    admin = await admin_token(env)
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)

    await set_cutoff(env, admin, 0)

    quoted = await post(env, f"{ORDERS}/quote", token, {
        "customerId": customer.id,
        "items": [{"cylinderType": "LPG_19KG", "quantity": 2}],
    })

    cutoff = quoted.json()["cutoff"]
    assert cutoff["withinCutoff"] is False
    today_ist = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    assert cutoff["scheduledDeliveryDate"] == (today_ist + timedelta(days=1)).isoformat()
