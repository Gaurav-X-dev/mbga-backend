"""The shells a customer is still holding, across visits.

A customer took two 19 KG last month and kept the empties. Today they are ordering 5 KG. The
driver is standing at their gate - the one moment those 19 KG shells can be collected - and
his screen listed 5 KG and nothing else, with `customerPreviousDue` hard-coded to zero on
every line. Sending the 19 KG back on `/confirm` was refused outright: it was not on today's
order.

So the shells came back only when somebody happened to remember them, and the platform's own
count of what was out with customers was never right.
"""

import pytest
from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.inventory.models import StockMovement
from tests.integration.deliveries.conftest import ORDERS
from tests.integration.driver.conftest import (
    DRIVER_DELIVERIES,
    dispatch_staff,
    driver_token,
    make_customer,
    make_driver,
    place_order,
    price_cylinders,
    refill,
    settings_overrides,  # noqa: F401 - fixture
)
from tests.integration.driver.test_driver_payment import confirmation

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

VAN = "MP09 GH 4521"


async def a_customer(env):
    """Staff, a priced month, stock of both sizes, one customer and one driver."""
    token, merchant, _user = await dispatch_staff(env)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    for cylinder in ("LPG_5KG", "LPG_19KG"):
        await refill(env, token, cylinder, 60)
    driver = await make_driver(env, merchant)
    return token, merchant, customer, driver


async def visit(env, token, customer, driver, *lines):
    """Place, confirm and dispatch one order. Returns `(drivers_token, slip_id, otp)`."""
    order = await place_order(env, token, customer.id, *lines)
    confirmed = await env.post(
        f"{ORDERS}/{order['id']}/confirm",
        token,
        {"delivery": {"vehicleNumber": VAN, "driverUserId": driver.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    slip_id = confirmed.json()["deliverySlipId"]
    drivers = await driver_token(env, driver)
    out = await env.post(f"{DRIVER_DELIVERIES}/{slip_id}/out-for-delivery", drivers, {})
    assert out.status_code == 200, out.text
    return drivers, slip_id, out.json()["devConfirmationCode"]


async def complete(env, drivers, slip_id, otp, delivered, empties):
    confirmed = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation(delivered, amount=0, empties=empties),
    )
    assert confirmed.status_code == 200, confirmed.text
    verified = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/verify-customer-otp", drivers, {"otp": otp}
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def returns_of(env, drivers, slip_id) -> dict[str, dict]:
    today = await env.get(f"{DRIVER_DELIVERIES}/today", drivers)
    assert today.status_code == 200, today.text
    row = next(r for r in today.json() if r["id"] == slip_id)
    return {line["cylinderType"]: line for line in row["emptyReturns"]}


# --- What the driver is shown -----------------------------------------------------------------


async def test_a_size_from_an_earlier_visit_is_listed(env):
    """The case this was built for: 19 KG owed, 5 KG being delivered."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])

    _drivers, second, _otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    lines = await returns_of(env, drivers, second)
    assert "LPG_19KG" in lines
    assert lines["LPG_19KG"]["customerPreviousDue"] == 2


async def test_the_size_being_delivered_is_still_listed(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    lines = await returns_of(env, drivers, second)
    assert lines["LPG_5KG"]["currentOrderQuantity"] == 1
    assert lines["LPG_5KG"]["customerPreviousDue"] == 0


async def test_today_and_earlier_are_added_up(env):
    """Same size on both visits: the driver asks for all of them at once."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_19KG", 3))

    line = (await returns_of(env, drivers, second))["LPG_19KG"]
    assert (line["currentOrderQuantity"], line["customerPreviousDue"]) == (3, 2)
    assert line["expectedQuantity"] == 5


async def test_shells_already_returned_are_not_asked_for_again(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [("LPG_19KG", 2)])

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    assert "LPG_19KG" not in await returns_of(env, drivers, second)


async def test_a_partial_return_leaves_only_the_difference(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 3))
    await complete(env, drivers, first, otp, [("LPG_19KG", 3)], [("LPG_19KG", 1)])

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    assert (await returns_of(env, drivers, second))["LPG_19KG"]["customerPreviousDue"] == 2


async def test_todays_own_cylinders_are_not_counted_as_owed(env):
    """They are being handed over on this very visit; asking for them back is nonsense."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, _otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    line = (await returns_of(env, drivers, slip_id))["LPG_19KG"]
    assert line["customerPreviousDue"] == 0
    assert line["expectedQuantity"] == 2


async def test_one_customers_shells_are_not_asked_of_another(env):
    """The balance follows the customer, not the merchant or the round."""
    token, merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])
    neighbour = await make_customer(env, merchant)

    _d, theirs, _o = await visit(env, token, neighbour, driver, ("LPG_5KG", 1))

    assert "LPG_19KG" not in await returns_of(env, drivers, theirs)


async def test_a_slip_still_on_the_van_does_not_count_yet(env):
    """Nothing has crossed the gate until the customer's code is read out."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, _first, _otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    assert "LPG_19KG" not in await returns_of(env, drivers, second)


# --- What the driver may hand in ---------------------------------------------------------------


async def test_a_shell_not_on_todays_order_can_be_collected(env):
    """Refused outright before, which is why the 19 KG never came back."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])

    _d, second, otp2 = await visit(env, token, customer, driver, ("LPG_5KG", 1))
    receipt = await complete(
        env, drivers, second, otp2, [("LPG_5KG", 1)], [("LPG_5KG", 1), ("LPG_19KG", 2)]
    )

    collected = {i["cylinderType"]: i["quantity"] for i in receipt["emptyCollectedItems"]}
    assert collected == {"LPG_5KG": 1, "LPG_19KG": 2}


async def test_collecting_them_clears_the_balance(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])
    _d, second, otp2 = await visit(env, token, customer, driver, ("LPG_5KG", 1))
    await complete(env, drivers, second, otp2, [("LPG_5KG", 1)], [("LPG_19KG", 2)])

    _d3, third, _o3 = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    assert "LPG_19KG" not in await returns_of(env, drivers, third)


async def test_the_extra_line_sells_nothing(env):
    """A shell coming back is not a cylinder going out: the line is booked at zero."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 2))
    await complete(env, drivers, first, otp, [("LPG_19KG", 2)], [])
    _d, second, otp2 = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    await complete(env, drivers, second, otp2, [("LPG_5KG", 1)], [("LPG_19KG", 2)])

    async with env.sessions() as db:
        row = await db.scalar(
            select(DeliverySlipItem).where(
                DeliverySlipItem.slip_id == second,
                DeliverySlipItem.cylinder_type == "LPG_19KG",
            )
        )
    assert (row.quantity, row.delivered_quantity, row.empties_collected) == (0, 0, 2)


# --- Where the refusal lands ---------------------------------------------------------------------


async def test_too_many_empties_is_refused_on_the_empties_screen(env):
    """Not held back until the customer's code.

    The ceiling used to be reached only at `verify-customer-otp`. A driver who typed the wrong
    count got through the empties screen, asked the customer to read out their code, and was
    then refused - and the delivery app showed it as an OTP mismatch. Production hit exactly
    this: one hippo delivered, five claimed back, `confirmation_attempts` still 0.
    """
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, _otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation([("LPG_5KG", 1)], amount=0, empties=[("LPG_5KG", 5)]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"][0]["code"] == "empties_out_of_range"


async def test_the_ceiling_counts_what_the_customer_owes(env):
    """The same count passes once those shells are genuinely out with them."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, first, otp = await visit(env, token, customer, driver, ("LPG_19KG", 4))
    await complete(env, drivers, first, otp, [("LPG_19KG", 4)], [])

    _d, second, _o = await visit(env, token, customer, driver, ("LPG_5KG", 1))
    response = await env.post(
        f"{DRIVER_DELIVERIES}/{second}/confirm",
        drivers,
        confirmation([("LPG_5KG", 1)], amount=0, empties=[("LPG_19KG", 4), ("LPG_5KG", 1)]),
    )

    assert response.status_code == 200, response.text


async def test_a_refused_count_spends_no_otp_attempt(env):
    """What made it read as an OTP problem: the code was never reached."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, _otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation([("LPG_5KG", 1)], amount=0, empties=[("LPG_5KG", 9)]),
    )

    async with env.sessions() as db:
        attempts = await db.scalar(
            select(DeliverySlip.confirmation_attempts).where(DeliverySlip.id == slip_id)
        )
    assert attempts == 0


# --- What the godown screen prints ---------------------------------------------------------------


async def slip_number_of(env, slip_id: str) -> str:
    async with env.sessions() as db:
        return await db.scalar(
            select(DeliverySlip.slip_number).where(DeliverySlip.id == slip_id)
        )


async def test_a_handover_leaves_a_readable_line_in_the_ledger(env):
    """The Warehouse Stock screen printed a slip's uuid in front of the order number, because
    automatic movements carried no note and put the database key in `referenceId`."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_5KG", 2))

    await complete(env, drivers, slip_id, otp, [("LPG_5KG", 2)], [("LPG_5KG", 1)])

    number = await slip_number_of(env, slip_id)
    async with env.sessions() as db:
        notes = list(
            await db.scalars(
                select(StockMovement.note).where(StockMovement.reference_id == number)
            )
        )
    assert notes, "the handover booked no stock movement"
    assert all(note and "ORD-" in note for note in notes)


async def test_the_line_names_the_customer(env):
    """Whose cylinders left the godown is the question the screen is read with."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    await complete(env, drivers, slip_id, otp, [("LPG_5KG", 1)], [])

    number = await slip_number_of(env, slip_id)
    async with env.sessions() as db:
        note = await db.scalar(
            select(StockMovement.note).where(StockMovement.reference_id == number)
        )
    assert customer.name in note


async def test_the_reference_is_the_slip_number_not_a_uuid(env):
    """`referenceId` is free text meant to be read - a challan number on a refill, a vehicle
    number on a transfer. A uuid there put 36 characters of database key on the screen in
    front of the order number, on every automatic row."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    await complete(env, drivers, slip_id, otp, [("LPG_5KG", 1)], [])

    number = await slip_number_of(env, slip_id)
    async with env.sessions() as db:
        references = set(
            await db.scalars(
                select(StockMovement.reference_id).where(
                    StockMovement.reference_id == number
                )
            )
        )
    assert references == {number}
    assert slip_id not in references


# --- What a refused handover now reads like -------------------------------------------------------


async def test_the_refusal_reads_as_a_sentence_about_empties(env):
    """Not "Some fields are missing or invalid", which is what three separate incidents were
    reported as this week."""
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, _otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation([("LPG_5KG", 1)], amount=0, empties=[("LPG_5KG", 9)]),
    )

    detail = response.json()["detail"]
    assert detail["message"] == detail["fields"][0]["message"]
    assert "missing" not in detail["message"].lower()


async def test_a_wrong_code_reads_as_a_wrong_code(env):
    token, _merchant, customer, driver = await a_customer(env)
    drivers, slip_id, _otp = await visit(env, token, customer, driver, ("LPG_5KG", 1))
    await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/confirm",
        drivers,
        confirmation([("LPG_5KG", 1)], amount=0, empties=[]),
    )

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_id}/verify-customer-otp", drivers, {"otp": "0000"}
    )

    assert response.status_code == 422, response.text
    assert "otp" in response.json()["detail"]["message"].lower()
