"""What the delivery slice will write, and what the bell gets told (spec §10, §18.6, §18.8).

`dispatch` and `collect_empties` have no endpoint - they are refused on `POST /movements` on
purpose - so they are tested directly against the ledger. They are written now, with tests,
because the rule they have to keep is the hardest one in the module and the delivery module
should not have to discover it: **a dispatch that is short on any line changes nothing at all.**

The notification tests pin the other easily-got-wrong rule: staff are told when stock crosses
the reorder line, once per crossing, and not on every movement while it is already low.
"""

import pytest
from sqlalchemy import func, select

from app.modules.inventory.constants import MovementReference
from app.modules.inventory.ledger import StockLedger
from app.modules.inventory.models import StockMovement
from app.modules.pricing.constants import CylinderType
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.models import NotificationOutbox
from tests.integration.inventory.conftest import (
    counts,
    godown_staff,
    record,
    recorded,
    refill,
    snapshot,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

NINETEEN = CylinderType.LPG_19KG
FIVE = CylinderType.LPG_5KG


async def dispatch(env, merchant, lines: dict, *, reference_id: str = "DS-0148"):
    """Run one dispatch on its own transaction, the way a delivery endpoint would."""
    async with env.sessions() as session:
        ledger = StockLedger(session, merchant.id)
        applied = await ledger.dispatch(
            lines,
            reference_id=reference_id,
            recorded_by_user_id=None,
            recorded_by_name="Mohan Lal",
        )
        await session.commit()
        return applied


async def collect(env, merchant, lines: dict, *, reference_id: str = "DS-0148"):
    async with env.sessions() as session:
        ledger = StockLedger(session, merchant.id)
        applied = await ledger.collect_empties(
            lines,
            reference_id=reference_id,
            recorded_by_user_id=None,
            recorded_by_name="Mohan Lal",
        )
        await session.commit()
        return applied


async def movement_count(env, merchant) -> int:
    return int(
        await env.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.merchant_id == merchant.id)
        )
        or 0
    )


# --- Dispatch ---------------------------------------------------------------------------------


async def test_a_dispatch_takes_filled_stock_out(env):
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)

    applied = await dispatch(env, merchant, {NINETEEN: 4})

    assert len(applied) == 1
    assert counts(await snapshot(env, token)) == (56, 0, 0)


async def test_a_dispatch_records_itself_against_the_slip(env):
    """"referenceType": "DELIVERY" - which is how a slip is reconciled back to the counts."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)

    await dispatch(env, merchant, {NINETEEN: 4}, reference_id="DS-0148")

    row = await env.scalar(
        select(StockMovement).where(
            StockMovement.merchant_id == merchant.id,
            StockMovement.movement_type == "DISPATCHED",
        )
    )
    assert row.reference_type == MovementReference.DELIVERY.value
    assert row.reference_id == "DS-0148"
    assert (row.delta_filled, row.quantity) == (-4, 4)
    assert row.recorded_by_name == "Mohan Lal"


async def test_a_short_line_refuses_the_whole_dispatch(env):
    """Spec §10's message, verbatim: it is shown to the person trying to dispatch."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=3)

    with pytest.raises(ApiError) as caught:
        await dispatch(env, merchant, {NINETEEN: 4})

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "INSUFFICIENT_STOCK"
    assert caught.value.detail["message"] == (
        "Not enough filled 19 KG in stock (3 available, 4 needed). Record a refill first."
    )


async def test_a_short_line_leaves_every_other_line_untouched(env):
    """The rule the delivery module must not have to discover (spec §10, §18.6).

    Applying line by line would leave a two-line dispatch half done: the 5 KG gone from the
    godown, three movements on the ledger, and no delivery to explain any of it.
    """
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_5KG", quantity=40)
    await refill(env, token, cylinder="LPG_19KG", quantity=2)
    before = await movement_count(env, merchant)

    with pytest.raises(ApiError):
        await dispatch(env, merchant, {FIVE: 10, NINETEEN: 4})

    body = await snapshot(env, token)
    assert counts(body, "LPG_5KG") == (40, 0, 0), "the sufficient line must not have moved"
    assert counts(body, "LPG_19KG") == (2, 0, 0)
    assert await movement_count(env, merchant) == before, "nothing was written"


async def test_a_dispatch_of_several_lines_writes_one_movement_each(env):
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_5KG", quantity=40)
    await refill(env, token, cylinder="LPG_19KG", quantity=40)

    applied = await dispatch(env, merchant, {FIVE: 6, NINETEEN: 2})

    assert len(applied) == 2
    body = await snapshot(env, token)
    assert counts(body, "LPG_5KG") == (34, 0, 0)
    assert counts(body, "LPG_19KG") == (38, 0, 0)


async def test_a_dispatch_may_empty_the_godown_exactly(env):
    """Boundary: needing exactly what is there is sufficient, not short."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=4)

    await dispatch(env, merchant, {NINETEEN: 4})

    assert counts(await snapshot(env, token)) == (0, 0, 0)


async def test_dispatching_a_cylinder_never_stocked_is_refused(env):
    """Zero available, four needed - the same refusal, without a row having to exist first."""
    _token, merchant, _user = await godown_staff(env)

    with pytest.raises(ApiError) as caught:
        await dispatch(env, merchant, {NINETEEN: 4})

    assert "0 available" in caught.value.detail["message"]


# --- Empties coming back ----------------------------------------------------------------------


async def test_collected_empties_go_into_the_empty_bucket(env):
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=10)
    await dispatch(env, merchant, {NINETEEN: 4})

    await collect(env, merchant, {NINETEEN: 4})

    assert counts(await snapshot(env, token)) == (6, 4, 0)


async def test_collecting_empties_needs_no_stock_to_draw_from(env):
    """It only ever adds. Empties never collected are the delivery's `pendingPickup`, not a
    negative bucket here."""
    token, merchant, _user = await godown_staff(env)

    await collect(env, merchant, {NINETEEN: 3})

    assert counts(await snapshot(env, token)) == (0, 3, 0)


async def test_the_full_delivery_cycle_reconciles(env):
    """Sixty in, four out, four empties back: the ledger and the counts agree at every step."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=60)
    await dispatch(env, merchant, {NINETEEN: 4})
    await collect(env, merchant, {NINETEEN: 4})

    filled, empty, damaged = counts(await snapshot(env, token))
    rows = list(
        await env.execute(
            select(StockMovement.delta_filled, StockMovement.delta_empty, StockMovement.delta_damaged)
            .where(StockMovement.merchant_id == merchant.id)
        )
    )

    assert (filled, empty, damaged) == (56, 4, 0)
    assert sum(row.delta_filled for row in rows) == filled
    assert sum(row.delta_empty for row in rows) == empty


# --- The bell ---------------------------------------------------------------------------------


async def notifications_for(env, merchant) -> list[tuple[str, str, str]]:
    """(event_type, title, severity) of everything queued for this merchant."""
    rows = list(
        await env.execute(
            select(
                NotificationOutbox.event_type,
                NotificationOutbox.title,
                NotificationOutbox.severity,
            ).where(NotificationOutbox.recipient_id == merchant.id)
        )
    )
    return [(row.event_type, row.title, row.severity) for row in rows]


async def test_crossing_the_reorder_line_tells_staff(env):
    """19 KG's threshold is 120, so dropping from 130 to 118 crosses it."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=130)

    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=12)

    events = await notifications_for(env, merchant)
    assert ("STOCK_BELOW_THRESHOLD", "Stock below reorder threshold", "WARNING") in events


async def test_the_warning_carries_the_count_and_the_threshold(env):
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=130)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=12)

    body = await env.scalar(
        select(NotificationOutbox.body).where(
            NotificationOutbox.recipient_id == merchant.id,
            NotificationOutbox.event_type == "STOCK_BELOW_THRESHOLD",
        )
    )

    assert body == "19 KG filled stock is 118 against a threshold of 120. Plan a BPCL refill."


async def test_staff_are_not_told_again_on_every_movement_while_stock_is_low(env):
    """The crossing, not the state.

    A warning on each movement during a shortage is muted within a day - and then the one that
    matters is muted too.
    """
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, quantity=130)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=12)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=3)
    await recorded(env, token, type="MARKED_DAMAGED", fromBucket="filled", quantity=3)

    warnings = [event for event in await notifications_for(env, merchant) if event[0] == "STOCK_BELOW_THRESHOLD"]

    assert len(warnings) == 1


async def test_a_refill_that_stays_above_the_line_tells_nobody(env):
    token, merchant, _user = await godown_staff(env)

    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=10)

    assert await notifications_for(env, merchant) == []


async def test_running_out_entirely_is_critical_rather_than_a_warning(env):
    """Orders for that cylinder cannot be delivered at all, so it is not a planning matter."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=6)

    await recorded(
        env, token, cylinderType="LPG_422KG_HIPPO", type="MARKED_DAMAGED", fromBucket="filled", quantity=6
    )

    events = await notifications_for(env, merchant)
    assert ("STOCK_OUT", "Out of stock", "CRITICAL") in events
    assert not [event for event in events if event[0] == "STOCK_BELOW_THRESHOLD"], (
        "empty is reported once, as critical, not twice"
    )


async def test_the_same_cylinder_can_warn_again_after_it_is_restocked(env):
    """Keyed on the movement, so a second shortage is a second notification.

    Keyed on the cylinder type it would collide on the outbox's uniqueness constraint and
    September's shortage would silently suppress November's.
    """
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=6)
    # 422 KG Hippo's threshold is 4: 6 -> 3 crosses it.
    await recorded(
        env, token, cylinderType="LPG_422KG_HIPPO", type="MARKED_DAMAGED", fromBucket="filled", quantity=3
    )
    # Restocked well above the line, then taken back under it.
    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=6)
    await recorded(
        env, token, cylinderType="LPG_422KG_HIPPO", type="MARKED_DAMAGED", fromBucket="filled", quantity=6
    )

    warnings = [event for event in await notifications_for(env, merchant) if event[0] == "STOCK_BELOW_THRESHOLD"]

    assert len(warnings) == 2, "both crossings were reported"


async def test_a_refused_movement_queues_no_notification(env):
    """The outbox row is written in the movement's transaction, so it rolls back with it."""
    token, merchant, _user = await godown_staff(env)
    await refill(env, token, cylinder="LPG_422KG_HIPPO", quantity=5)

    await record(
        env, token, cylinderType="LPG_422KG_HIPPO", type="MARKED_DAMAGED", fromBucket="filled", quantity=9
    )

    assert await notifications_for(env, merchant) == []
