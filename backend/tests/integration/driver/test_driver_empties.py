"""Which size of empty cylinder came back, and how many of each.

The slip has always kept one number across every type, which is what the stock ledger books.
It was all the platform knew, so the receipt had no per-type figures to print and listed the
**delivered** lines in the empties column instead. A handover of two 5 KG and one 19 KG, with
two empties taken, printed "Total: 2" above rows adding to 3 - which is how it was found.

The app had been sending the breakdown on `/confirm` all along; it was summed on arrival and
thrown away.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import confirmation, handover

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def empties_of(env, slip) -> dict[str, int | None]:
    async with env.sessions() as db:
        items = list(
            await db.scalars(
                select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip["id"])
            )
        )
    return {row.cylinder_type: row.empties_collected for row in items}


async def test_the_breakdown_is_kept_per_size(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_5KG", 2), ("LPG_19KG", 1))

    await handover(
        env,
        token,
        slip,
        [("LPG_5KG", 2), ("LPG_19KG", 1)],
        amount=0,
        empties=[("LPG_5KG", 2)],
    )

    assert await empties_of(env, slip) == {"LPG_5KG": 2, "LPG_19KG": 0}


async def test_the_slips_own_total_still_agrees(env):
    """The ledger books one number; the breakdown sits beneath it and must add up to it."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_5KG", 2), ("LPG_19KG", 1))

    await handover(
        env,
        token,
        slip,
        [("LPG_5KG", 2), ("LPG_19KG", 1)],
        amount=0,
        empties=[("LPG_5KG", 2), ("LPG_19KG", 1)],
    )

    stored = await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))
    per_type = await empties_of(env, slip)
    assert stored.empties_collected == 3
    assert sum(per_type.values()) == 3


async def test_the_receipt_lists_the_empties_not_the_delivery(env):
    """The bug exactly: two empties taken, rows that added to three."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_5KG", 2), ("LPG_19KG", 1))
    await handover(
        env,
        token,
        slip,
        [("LPG_5KG", 2), ("LPG_19KG", 1)],
        amount=0,
        empties=[("LPG_5KG", 2)],
    )

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [(row["cylinderType"], row["quantity"]) for row in body["emptyItems"]] == [
        ("LPG_5KG", 2)
    ]
    # Delivered is still its own list, and still the full handover.
    assert sum(row["quantity"] for row in body["deliveredItems"]) == 3


async def test_the_rows_add_up_to_the_total_shown_beside_them(env):
    """What the receipt failed at. Both figures come from the same place now."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_5KG", 2), ("LPG_19KG", 1))

    verified = await handover(
        env,
        token,
        slip,
        [("LPG_5KG", 2), ("LPG_19KG", 1)],
        amount=0,
        empties=[("LPG_5KG", 2)],
    )

    body = verified.json()
    assert body["totalEmptyCollectedQuantity"] == 2
    assert sum(row["quantity"] for row in body["emptyCollectedItems"]) == 2


async def test_an_empty_carries_no_price(env):
    """It is returned, not sold - a price against it reads as a charge."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0, empties=[("LPG_19KG", 2)])

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)

    row = detail.json()["emptyItems"][0]
    assert row["unitPrice"] is None
    assert row["totalPrice"] is None


async def test_collecting_no_empties_lists_none(env):
    """A first-time customer has nothing to return, and zero rows say that better than zeroes."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0, empties=[])

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)
    assert detail.json()["emptyItems"] == []


async def test_more_empties_than_cylinders_delivered_is_allowed(env):
    """A part delivery still takes back the shells the van came for.

    The ceiling is what the slip is answerable for plus what the customer is already holding -
    not what was handed over on this doorstep. A driver who leaves one of two cylinders may
    still take two empties.

    Beyond that ceiling it is refused, and refused HERE: see
    `test_customer_empties.py::test_too_many_empties_is_refused_on_the_empties_screen`.
    """
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 1)], amount=0, empties=[("LPG_19KG", 2)]),
    )

    assert response.status_code == 200, response.text
    assert (await empties_of(env, slip)) == {"LPG_19KG": 2}


async def test_an_empty_of_a_type_not_on_the_slip_is_recorded(env):
    """It used to be refused, which is what kept last month's shells in the customer's yard.

    A size the customer is handing back but did not order today gets a line of its own with
    nothing allocated against it. See `test_customer_empties.py` for the balance that decides
    how many of them the driver may take.
    """
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/confirm",
        token,
        confirmation([("LPG_19KG", 2)], amount=0, empties=[("LPG_5KG", 1)]),
    )

    assert response.status_code == 200, response.text
    assert await empties_of(env, slip) == {"LPG_19KG": 0, "LPG_5KG": 1}
