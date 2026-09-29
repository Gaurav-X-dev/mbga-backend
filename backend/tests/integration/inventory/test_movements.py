"""Recording movements, and the ledger they build (spec §11.2, §11.3).

The property under test throughout is spec §18.6's: **counts and ledger always agree**. So most
of these assert both sides - what the card says and what the history says - because a module
that gets one right and the other wrong is the failure that takes a month to notice.
"""

import pytest
from sqlalchemy import func, select

from app.modules.inventory.models import StockMovement
from tests.integration.inventory.conftest import (
    MOVEMENTS,
    VIEW_ONLY,
    code_of,
    counts,
    godown_staff,
    record,
    recorded,
    refill,
    snapshot,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def history(env, token: str, **params) -> list[dict]:
    response = await env.get(MOVEMENTS, token, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


# --- Each type's effect on the counts ---------------------------------------------------------


async def test_a_refill_adds_to_filled(env):
    token, _merchant, _user = await godown_staff(env)

    movement = await refill(env, token, quantity=60, referenceId="BPCL/CH/22871", note="Morning refill truck")

    assert movement["type"] == "RECEIVED_FILLED"
    assert movement["quantity"] == 60
    assert movement["deltas"] == {"filled": 60}
    assert movement["referenceType"] == "CHALLAN"
    assert movement["referenceId"] == "BPCL/CH/22871"
    assert counts(await snapshot(env, token)) == (60, 0, 0)


async def test_a_plant_return_takes_empties_out_of_the_godown(env):
    """Out of the building entirely: one bucket down and nothing up."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=20)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=8)

    movement = await recorded(
        env, token, type="SENT_TO_PLANT", fromBucket="damaged", quantity=5, referenceId="MP09 GH 4521"
    )

    assert movement["deltas"] == {"damaged": -5}
    assert movement["quantity"] == 5, "quantity is always positive; the delta carries direction"
    assert counts(await snapshot(env, token)) == (12, 0, 3)


async def test_marking_damaged_moves_cylinders_sideways(env):
    """Two buckets in one movement, and the total in the godown does not change."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=30)

    movement = await recorded(
        env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=2, note="Valve leak"
    )

    assert movement["deltas"] == {"filled": -2, "damaged": 2}
    filled, empty, damaged = counts(await snapshot(env, token))
    assert (filled, empty, damaged) == (28, 0, 2)
    assert filled + empty + damaged == 30, "nothing physically left the godown"


async def test_a_correction_moves_a_bucket_to_the_counted_figure(env):
    """`bucket += (newCount - current)` (spec §11.3)."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_5KG", quantity=90)

    movement = await recorded(
        env,
        token,
        type="CORRECTION",
        cylinderType="LPG_5KG",
        bucket="filled",
        newCount=87,
        note="Physical audit: 3 short vs register",
    )

    assert movement["deltas"] == {"filled": -3}
    assert movement["quantity"] == 3, "the size of the correction, not the new count"
    assert counts(await snapshot(env, token), "LPG_5KG") == (87, 0, 0)


async def test_a_correction_upwards_is_the_same_movement(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=40)

    movement = await recorded(
        env, token, type="CORRECTION", bucket="filled", newCount=43, note="Found behind the shed"
    )

    assert movement["deltas"] == {"filled": 3}
    assert counts(await snapshot(env, token)) == (43, 0, 0)


async def test_a_correction_records_what_the_count_was(env):
    """"filled -3" alone cannot say whether the count was 240 or 24."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=40)
    await recorded(env, token, type="CORRECTION", bucket="filled", newCount=37, note="Audit")

    row = await env.scalar(
        select(StockMovement).where(
            StockMovement.merchant_id == merchant.id,
            StockMovement.movement_type == "CORRECTION",
        )
    )

    assert (row.previous_count, row.new_count) == (40, 37)
    assert row.bucket == "filled"


async def test_a_correction_that_changes_nothing_is_refused(env):
    """A ledger row saying a count was audited and left alone reads as a change."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=40)

    response = await record(
        env, token, type="CORRECTION", bucket="filled", newCount=40, note="Audit"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["message"] == "No change"


async def test_a_correction_can_take_a_bucket_to_zero(env):
    """A godown really can be empty, and an audit has to be able to say so."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=12)

    await recorded(env, token, type="CORRECTION", bucket="filled", newCount=0, note="All dispatched")

    assert counts(await snapshot(env, token)) == (0, 0, 0)


# --- Nothing may go negative ------------------------------------------------------------------


async def test_a_movement_that_would_go_negative_is_refused(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=3)

    response = await record(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=4)

    assert response.status_code == 409
    assert code_of(response) == "INSUFFICIENT_STOCK"
    assert "3" in response.json()["detail"]["message"]


async def test_a_refused_movement_changes_nothing_and_writes_nothing(env):
    """A negative count is not a smaller number - it is a warehouse that has lost track.

    The whole transaction has to be rolled back, or the ledger gains a row for a movement that
    never happened and the two sides stop agreeing.
    """
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=3)

    await record(env, token, type="SENT_TO_PLANT", fromBucket="empty", quantity=1)

    assert counts(await snapshot(env, token)) == (3, 0, 0)
    written = await env.scalar(
        select(func.count())
        .select_from(StockMovement)
        .where(StockMovement.merchant_id == merchant.id)
    )
    assert written == 1, "only the refill is on the ledger"


async def test_an_empty_bucket_cannot_be_drawn_from_at_all(env):
    token, _merchant, _user = await godown_staff(env)

    response = await record(env, token, type="SENT_TO_PLANT", fromBucket="empty", quantity=1)

    assert response.status_code == 409


# --- The ledger explains the counts -----------------------------------------------------------


async def test_every_count_change_has_a_movement_behind_it(env):
    """Spec §18.6, stated as a test: sum the ledger, get the card."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)
    await refill(env, token, quantity=20)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=5)
    await recorded(env, token, type="SENT_TO_PLANT", fromBucket="damaged", quantity=2)

    rows = await history(env, token)
    filled, empty, damaged = counts(await snapshot(env, token))

    assert (filled, empty, damaged) == (75, 0, 3)
    assert sum(row["deltas"].get("filled") or 0 for row in rows) == filled
    assert sum(row["deltas"].get("empty") or 0 for row in rows) == empty
    assert sum(row["deltas"].get("damaged") or 0 for row in rows) == damaged


async def test_the_history_is_newest_first(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=10, note="first")
    await refill(env, token, quantity=20, note="second")
    await refill(env, token, quantity=30, note="third")

    rows = await history(env, token)

    assert [row["note"] for row in rows] == ["third", "second", "first"]


async def test_the_history_can_be_filtered_by_cylinder(env):
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_19KG", quantity=10)
    await refill(env, token, cylinder="LPG_5KG", quantity=20)

    only_19 = await history(env, token, cylinderType="LPG_19KG")
    everything = await history(env, token, cylinderType="ALL")

    assert [row["cylinderType"] for row in only_19] == ["LPG_19KG"]
    assert len(everything) == 2


async def test_an_unknown_cylinder_filter_returns_nothing_rather_than_an_error(env):
    """The filter is a chip on a screen; a stale chip shows an empty list, not a dialog."""
    token, _merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=10)

    assert await history(env, token, cylinderType="LPG_NOT_A_TYPE") == []


async def test_the_history_respects_the_limit(env):
    token, _merchant, _user = await godown_staff(env)
    for quantity in (1, 2, 3):
        await refill(env, token, quantity=quantity)

    assert len(await history(env, token, limit=2)) == 2


async def test_a_movement_records_who_recorded_it(env):
    """From the session, never from the body - and kept on the row for when they have left."""
    token, _merchant, user = await godown_staff(env)

    movement = await refill(env, token, quantity=10)

    assert movement["recordedBy"] == "Test Manager"
    assert movement["recordedAt"].endswith("Z")
    assert user


async def test_one_merchants_ledger_is_not_anothers(env):
    mine_token, _mine, _u1 = await godown_staff(env)
    theirs_token, _theirs, _u2 = await godown_staff(env)
    await refill(env, theirs_token, quantity=60, note="theirs")

    assert await history(env, mine_token) == []
    assert [row["note"] for row in await history(env, theirs_token)] == ["theirs"]


# --- Permissions -------------------------------------------------------------------------------


async def test_recording_needs_the_adjust_permission(env):
    """Reading stock and changing it are separate rights (spec §2.1)."""
    token, _merchant, _user = await godown_staff(env, permissions=VIEW_ONLY)

    response = await record(env, token, type="RECEIVED_FILLED", quantity=10)

    assert response.status_code == 403
    assert code_of(response) == "PERMISSION_DENIED"


async def test_recording_needs_a_session(env):
    assert (await env.post(MOVEMENTS, json={"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 1})).status_code == 401


# --- Idempotency -------------------------------------------------------------------------------


async def test_a_retried_movement_is_not_booked_twice(env):
    """A godown phone on patchy wifi retries; the refill truck arrived once (spec §1)."""
    token, _merchant, _user = await godown_staff(env)
    body = {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 60}
    headers = {"Idempotency-Key": "refill-truck-1"}

    first = await env.post(MOVEMENTS, token, body, headers=headers)
    second = await env.post(MOVEMENTS, token, body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"], "the same movement, re-read"
    assert counts(await snapshot(env, token)) == (60, 0, 0), "booked once"


async def test_two_genuine_refills_both_count(env):
    """Without a key, or with a different one, two identical bodies are two truckloads."""
    token, _merchant, _user = await godown_staff(env)
    body = {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 60}

    await env.post(MOVEMENTS, token, body, headers={"Idempotency-Key": "truck-morning"})
    await env.post(MOVEMENTS, token, body, headers={"Idempotency-Key": "truck-afternoon"})

    assert counts(await snapshot(env, token)) == (120, 0, 0)


async def test_a_failed_attempt_does_not_burn_the_key(env):
    """A movement refused for lack of stock can be retried once the stock is there.

    The key is released as FAILED rather than COMPLETED, so the same request under the same key
    is allowed to run again - which is what a client that got a 409 will do after recording the
    refill it was told to record.
    """
    token, _merchant, _user = await godown_staff(env)
    headers = {"Idempotency-Key": "plant-return-1"}
    body = {"type": "SENT_TO_PLANT", "cylinderType": "LPG_19KG", "fromBucket": "empty", "quantity": 5}

    refused = await env.post(MOVEMENTS, token, body, headers=headers)
    await refill(env, token, quantity=10)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=6)
    await recorded(env, token, type="CORRECTION", bucket="empty", newCount=5, note="Empties counted in")
    retried = await env.post(MOVEMENTS, token, body, headers=headers)

    assert refused.status_code == 409
    assert retried.status_code == 201, "the key was released, not consumed"
    assert counts(await snapshot(env, token)) == (4, 0, 6)


async def test_the_same_key_cannot_be_reused_for_a_different_movement(env):
    """A key identifies one request. Reusing it for another is a client bug, not a retry.

    Letting it through is how a retry of "60 filled in" silently books "5 damaged out" instead.
    """
    token, _merchant, _user = await godown_staff(env)
    headers = {"Idempotency-Key": "same-key"}

    first = await env.post(
        MOVEMENTS, token, {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 60}, headers=headers
    )
    different = await env.post(
        MOVEMENTS, token, {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 5}, headers=headers
    )

    assert first.status_code == 201
    assert different.status_code == 409
    assert code_of(different) == "IDEMPOTENCY_KEY_REUSED"
    assert counts(await snapshot(env, token)) == (60, 0, 0)


# --- What the app may not post -----------------------------------------------------------------


@pytest.mark.parametrize("movement_type", ["DISPATCHED", "EMPTIES_COLLECTED"])
async def test_system_movements_are_refused_over_the_api(env, movement_type: str):
    """Otherwise filled stock could leave the godown with no delivery behind it."""
    token, _merchant, _user = await godown_staff(env)

    response = await record(env, token, type=movement_type, quantity=4)

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "type"


async def test_a_boolean_quantity_does_not_become_one_cylinder(env):
    """`bool` is an `int` in Python, so `true` would otherwise book a cylinder."""
    token, _merchant, _user = await godown_staff(env)

    response = await record(env, token, type="RECEIVED_FILLED", quantity=True)

    assert response.status_code == 422
    assert code_of(response) == "VALIDATION_ERROR"
    assert counts(await snapshot(env, token)) == (0, 0, 0)


async def test_an_unknown_cylinder_type_is_refused(env):
    token, _merchant, _user = await godown_staff(env)

    response = await record(env, token, cylinderType="LPG_999KG", type="RECEIVED_FILLED", quantity=1)

    assert response.status_code == 422
