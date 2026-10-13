"""What a customer still has of the merchant's cylinders, size by size.

A cylinder goes out full and is meant to come back empty, and the two halves of that trade
almost never happen on the same visit. A customer who took two 19 KG last month and is ordering
two 5 KG today still has the merchant's two 19 KG shells standing in their yard - and the
driver standing at their gate is the only person who can bring them back.

The driver's screen could not ask for them. `emptyReturns` was built from the lines of the
order being delivered, so it listed 5 KG and nothing else, and `customerPreviousDue` was
hard-coded to zero on every line. A size the customer was not re-ordering today was invisible,
which meant shells came back only when somebody happened to remember them.

**Derived, not stored.** The balance is read from the slips themselves rather than kept as a
running total on the customer, because a running total is a second copy of the truth and the
day it disagrees with the slips there is no way to tell which is wrong. The slips are the
record of what crossed the gate; this just adds them up.

Only `DELIVERED` slips count. A slip on a van has not changed anything yet, and a failed one
never did.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.constants import DeliveryStatus
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem


class CustomerEmpties:
    """The merchant's cylinders a customer is still holding, by type."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def outstanding(self, customer_id: str, *, ignoring: str | None = None) -> dict[str, int]:
        """`{cylinder_type: how many shells they still have}` - only sizes with one or more.

        `ignoring` leaves a slip out of the sum, for the slip being delivered right now: its own
        cylinders are today's handover and are counted on the screen separately, so including
        them here would ask the customer for the same shells twice.

        A size that balances, or that somehow came back more than it went out, is left out
        rather than reported as zero or negative. Nobody is asked for minus one cylinder, and a
        customer who returned a neighbour's shell is not owed one by the agency.
        """
        rows = await self.session.execute(
            select(
                DeliverySlipItem.cylinder_type,
                DeliverySlipItem.quantity,
                DeliverySlipItem.delivered_quantity,
                DeliverySlipItem.empties_collected,
            )
            .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
            .where(
                DeliverySlip.merchant_id == self.merchant_id,
                DeliverySlip.customer_id == customer_id,
                DeliverySlip.status == DeliveryStatus.DELIVERED.value,
                DeliverySlip.id != (ignoring or ""),
            )
        )

        balance: dict[str, int] = {}
        for cylinder_type, allocated, delivered, returned in rows:
            # `delivered_quantity` is null on a slip the office confirmed and on everything
            # older than the driver app. The stock ledger books the whole allocation in that
            # case, so this counts it the same way rather than reading the gap as nothing.
            given = allocated if delivered is None else delivered
            balance[cylinder_type] = balance.get(cylinder_type, 0) + given - (returned or 0)

        return {kind: due for kind, due in balance.items() if due > 0}
