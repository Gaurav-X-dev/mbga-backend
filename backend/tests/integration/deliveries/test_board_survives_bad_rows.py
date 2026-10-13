"""One unreadable row must not take out the delivery board.

A slip was found in production with `confirmation_method = ''`. Building the response called
`ConfirmationMethod('')`, which raises, so the whole of `GET /merchant/deliveries` answered 500 -
hiding every other delivery the merchant had, because of one row.

Writing is still strict: every path that creates a slip validates the method against the enum.
This is only about reading back a row that already exists, which is the case the enum cannot
speak for - a value written before a rule, or by hand during a migration.
"""

import pytest
from sqlalchemy import update

from app.modules.deliveries.models import DeliverySlip
from tests.integration.deliveries.conftest import (
    DELIVERIES,
    ready_to_dispatch,
    settings_overrides,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def blank_the_method(env, slip_id: str) -> None:
    """What was found in production, reproduced directly - no API can write this."""
    await env.execute(
        update(DeliverySlip).where(DeliverySlip.id == slip_id).values(confirmation_method="")
    )


async def test_the_board_still_lists_every_delivery(env):
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    _t2, _m2, _o2, other, _d2 = await ready_to_dispatch(env)
    await blank_the_method(env, slip["id"])

    listed = await env.get(f"{DELIVERIES}?limit=100", token)

    assert listed.status_code == 200, listed.text
    body = listed.json()
    rows = body["items"] if isinstance(body, dict) else body
    assert slip["id"] in {row["id"] for row in rows}
    assert other["id"]


async def test_the_bad_row_reads_as_no_method(env):
    """`NONE` is what a slip raised without one would have been given anyway."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)
    await blank_the_method(env, slip["id"])

    detail = await env.get(f"{DELIVERIES}/{slip['id']}", token)

    assert detail.status_code == 200, detail.text
    assert detail.json()["confirmationMethod"] == "NONE"


def test_writing_a_bad_method_is_still_refused():
    """The tolerance is for reading only. No request may put this value in the table."""
    from pydantic import ValidationError

    from app.modules.deliveries.schemas import CreateDeliverySlipRequest

    with pytest.raises(ValidationError):
        CreateDeliverySlipRequest(
            orderId="11111111-1111-1111-1111-111111111111",
            vehicleNumber="MP09 GH 4521",
            confirmationMethod="",
        )
