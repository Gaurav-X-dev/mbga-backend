"""The Warehouse Stock screen and its alerts (spec §11.1).

The snapshot is the screen's entire state, so these tests pin its shape as much as its numbers:
a card grid that changes length between merchants, or an alert that survives the refill that
fixed it, is a bug the app cannot work around.
"""

import pytest
from sqlalchemy import select

from app.modules.inventory.constants import DEFAULT_REORDER_THRESHOLDS
from app.modules.inventory.models import StockItem
from app.modules.pricing.constants import CylinderType
from tests.integration.inventory.conftest import (
    INVENTORY,
    VIEW_ONLY,
    card,
    code_of,
    counts,
    godown_staff,
    recorded,
    refill,
    snapshot,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


# --- Shape ----------------------------------------------------------------------------------


async def test_all_five_cylinder_types_are_always_returned(env):
    """The card grid has a fixed shape, so the app needs no placeholder logic."""
    token, _merchant, _user = await godown_staff(env)

    body = await snapshot(env, token)

    assert [item["cylinderType"] for item in body["items"]] == [
        cylinder.value for cylinder in CylinderType
    ]


async def test_a_merchant_who_has_never_recorded_stock_sees_zeros(env):
    token, _merchant, _user = await godown_staff(env)

    body = await snapshot(env, token)

    assert counts(body) == (0, 0, 0)
    assert card(body)["reorderThreshold"] == DEFAULT_REORDER_THRESHOLDS[CylinderType.LPG_19KG]
    # No movement stands behind those zeros, so there is no moment at which they were counted.
    assert card(body)["updatedAt"] is None


async def test_zeros_with_no_history_raise_no_alerts(env):
    """A cylinder a godown does not carry has not run out of anything.

    Five critical shortages on a merchant's first login would be technically true and
    operationally useless - and it would teach them to ignore the alert list on day one.
    """
    token, _merchant, _user = await godown_staff(env)

    assert (await snapshot(env, token))["alerts"] == []


async def test_a_card_carries_its_label_and_a_timestamp_once_it_is_stocked(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)

    item = card(await snapshot(env, token))

    assert item["cylinderLabel"] == "19 KG"
    assert item["filled"] == 60
    assert item["updatedAt"] is not None
    assert item["updatedAt"].endswith("Z"), "a naive timestamp reads as local time in the app"


async def test_the_snapshot_says_when_it_was_taken(env):
    token, _merchant, _user = await godown_staff(env)

    assert (await snapshot(env, token))["asOf"].endswith("Z")


# --- Alerts ---------------------------------------------------------------------------------


async def test_stock_below_the_threshold_raises_a_warning(env):
    """19 KG's default threshold is 120, so 60 is low but not yet critical."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)

    alerts = (await snapshot(env, token))["alerts"]

    assert [(alert["id"], alert["severity"]) for alert in alerts] == [
        ("SA-LOW-LPG_19KG", "WARNING")
    ]
    assert alerts[0]["message"] == "19 KG filled stock (60) is below the reorder threshold (120)."


async def test_stock_below_half_the_threshold_is_critical(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=30)

    assert (await snapshot(env, token))["alerts"][0]["severity"] == "CRITICAL"


async def test_a_refill_clears_the_alert_with_nothing_marking_it_resolved(env):
    """Alerts are derived from live counts (§18.6), which is the whole point of not storing them."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)
    assert (await snapshot(env, token))["alerts"], "precondition: the warning is showing"

    await refill(env, token, quantity=90)

    body = await snapshot(env, token)
    assert card(body)["filled"] == 150
    assert body["alerts"] == []


async def test_a_damaged_pile_is_reported_alongside_a_shortage(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=40)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=6)

    alerts = (await snapshot(env, token))["alerts"]

    assert [alert["severity"] for alert in alerts] == ["CRITICAL", "INFO"]
    assert alerts[1]["id"] == "SA-DMG-LPG_19KG"
    assert alerts[1]["message"] == "6 damaged 19 KG cylinders awaiting return to BPCL."


async def test_the_worst_alert_comes_first_across_cylinders(env):
    """The dashboard takes the top few (§14), so a critical shortage must not be pushed down."""
    token, _merchant, _user = await godown_staff(env)
    # 5 KG: threshold 150, so 140 is a warning. 422 KG Hippo: threshold 4, so 1 is critical.
    await refill(env, token, cylinder="LPG_5KG", quantity=140)
    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=1)

    severities = [alert["severity"] for alert in (await snapshot(env, token))["alerts"]]

    assert severities == ["CRITICAL", "WARNING"]


async def test_healthy_stock_raises_nothing(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=188)

    body = await snapshot(env, token)

    assert card(body)["filled"] == 188
    assert body["alerts"] == []


# --- Tenancy and access ----------------------------------------------------------------------


async def test_one_merchants_stock_is_invisible_to_another(env):
    """Not refused when asked for - not present at all. A competitor's operating position."""
    mine_token, _mine, _u1 = await godown_staff(env)
    theirs_token, theirs, _u2 = await godown_staff(env)
    await refill(env, theirs_token, quantity=60)

    body = await snapshot(env, mine_token)

    assert counts(body) == (0, 0, 0)
    assert body["alerts"] == []
    # Their own snapshot is unaffected by the read above.
    assert counts(await snapshot(env, theirs_token)) == (60, 0, 0)
    assert theirs


async def test_stock_rows_are_written_against_the_calling_merchant(env):
    """Belt and braces on the tenancy filter: the row itself carries the right merchant."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)

    rows = list(
        await env.execute(
            select(StockItem.cylinder_type).where(StockItem.merchant_id == merchant.id)
        )
    )

    # Exactly one row, for the one type that was stocked: the other four types are rendered
    # as zeros by the snapshot and are deliberately not written until they are used.
    assert [row.cylinder_type for row in rows] == ["LPG_19KG"]


async def test_reading_the_snapshot_needs_the_view_permission(env):
    token, _merchant, _user = await godown_staff(env, permissions=("orders.view",))

    response = await env.get(INVENTORY, token)

    assert response.status_code == 403
    assert code_of(response) == "PERMISSION_DENIED"


async def test_the_view_permission_alone_is_enough_to_read(env):
    token, _merchant, _user = await godown_staff(env, permissions=VIEW_ONLY)

    assert (await env.get(INVENTORY, token)).status_code == 200


async def test_the_warehouse_needs_a_session(env):
    assert (await env.get(INVENTORY)).status_code == 401


async def test_a_customer_token_cannot_reach_the_warehouse(env):
    """There is no customer-facing warehouse: these routes are not mounted on that channel."""
    from tests.integration.notifications.conftest import customer, staff

    _staff_token, merchant, _u = await staff(env)
    customer_token, _profile, _cu = await customer(env, merchant)

    # The merchant path with a customer token is a channel mismatch...
    mismatch = await env.get(INVENTORY, customer_token)
    # ...and the customer channel has no inventory route at all.
    missing = await env.get("/api/v1/customer/inventory", customer_token)

    assert mismatch.status_code == 403
    assert code_of(mismatch) == "CHANNEL_NOT_ALLOWED"
    assert missing.status_code == 404
