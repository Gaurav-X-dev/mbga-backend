"""Repeating a past order.

A reorder is one tap, which makes it the easiest place in the system to get something
quietly wrong. Three things must be true and none of them are automatic:

* **It is re-priced, never copied.** The source order's `unit_price` is what the customer
  paid *then*. Repeating it at last month's rate would sell below the current card, and the
  invoice would then disagree with the order. Every line goes back through the same
  `QuoteEngine` a fresh order uses.
* **It is re-validated.** Between the two orders the customer may have been suspended, may
  have changed from INDUSTRIAL to RETAIL (so the Hippo line is no longer theirs to buy), the
  quantity limits may have moved, or a cylinder may have been dropped from the price card.
  The source order proves none of that is still true.
* **It is re-sited.** The delivery site on the old order may have been deactivated or
  removed. An industrial reorder with a dead site has to ask for a new one rather than
  silently deliver to the registered address.

This module works out what *would* happen, without writing anything. The service uses the
same plan for the preview the app shows and for the order it then places, so the confirm
sheet and the placement can never disagree.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.constants import CustomerType
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.orders.constants import ORDER_LABELS, QUANTITY_LIMITS, REGISTERED_ADDRESS_LABEL
from app.modules.orders.models import Order, OrderItem
from app.modules.orders.schemas import OrderLineRequest
from app.modules.pricing.constants import INDUSTRIAL_ONLY_CYLINDERS, CylinderType

# Reasons the app renders verbatim next to a dropped line.
UNKNOWN_TYPE = "This cylinder is no longer offered."
INDUSTRIAL_ONLY = "This cylinder is only available to industrial customers."
OVER_LIMIT = "The maximum for this cylinder has changed. Reduce the quantity to reorder."

SITE_GONE = "The delivery site on the original order is no longer available. Choose another site."


@dataclass(frozen=True)
class DroppedLine:
    """A source line that cannot be repeated, with the sentence explaining why."""

    cylinder_type: CylinderType
    quantity: int
    reason: str

    @property
    def label(self) -> str:
        return ORDER_LABELS[self.cylinder_type]


@dataclass
class ReorderPlan:
    """What a repeat of `source` would look like today."""

    source: Order
    customer: CustomerProfile
    # The basket that can still be ordered, as request lines ready for the normal path.
    items: list[OrderLineRequest] = field(default_factory=list)
    dropped: list[DroppedLine] = field(default_factory=list)
    site: CustomerDeliverySite | None = None
    site_required_but_missing: bool = False

    @property
    def usable(self) -> bool:
        """Whether this plan can be placed as it stands."""
        return bool(self.items) and not self.dropped and not self.site_required_but_missing

    @property
    def site_name(self) -> str:
        return self.site.name if self.site else REGISTERED_ADDRESS_LABEL


class ReorderPlanner:
    """Builds the plan. Reads only - nothing here writes or commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def plan(
        self,
        source: Order,
        customer: CustomerProfile,
        *,
        items: list[OrderLineRequest] | None = None,
        delivery_site_id: str | None = None,
    ) -> ReorderPlan:
        """Work out what repeating `source` means for `customer` right now.

        `items` and `delivery_site_id` are the client's overrides: when the preview has
        already told the app a line cannot be repeated, it sends the adjusted basket rather
        than sending the user back through the whole Create Order screen.
        """
        basket = items if items is not None else await self._source_basket(source)
        plan = ReorderPlan(source=source, customer=customer)
        customer_type = (customer.customer_type or "").upper()

        for line in basket:
            reason = self._why_not(line, customer_type)
            if reason is None:
                plan.items.append(line)
            else:
                plan.dropped.append(
                    DroppedLine(cylinder_type=line.cylinder_type, quantity=line.quantity, reason=reason)
                )

        plan.site = await self._resolve_site(source, customer, delivery_site_id)
        # An industrial customer always needs a live site. The source order's may have been
        # deactivated since, which is not something the customer can see from the old order.
        plan.site_required_but_missing = (
            customer_type == CustomerType.INDUSTRIAL.value and plan.site is None
        )
        return plan

    async def _source_basket(self, source: Order) -> list[OrderLineRequest]:
        """The source order's lines, in the order they were placed."""
        rows = await self.session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == source.id)
            .order_by(OrderItem.position, OrderItem.id)
        )
        basket: list[OrderLineRequest] = []
        for row in rows:
            try:
                cylinder_type = CylinderType(row.cylinder_type)
            except ValueError:
                # A type retired since the order was placed. It is reported as dropped by
                # `_why_not` below, which needs a known enum member - so it is carried
                # through as a raw marker instead.
                basket.append(_retired_line(row))
                continue
            basket.append(
                OrderLineRequest.model_construct(cylinder_type=cylinder_type, quantity=row.quantity)
            )
        return basket

    @staticmethod
    def _why_not(line: OrderLineRequest, customer_type: str) -> str | None:
        """The reason this line cannot be repeated, or None when it can."""
        if not isinstance(line.cylinder_type, CylinderType):
            return UNKNOWN_TYPE
        if line.cylinder_type in INDUSTRIAL_ONLY_CYLINDERS and customer_type != CustomerType.INDUSTRIAL.value:
            # The customer was industrial when they ordered this and is not any more.
            return INDUSTRIAL_ONLY
        minimum, maximum = QUANTITY_LIMITS[line.cylinder_type]
        if not minimum <= line.quantity <= maximum:
            return OVER_LIMIT
        return None

    async def _resolve_site(
        self, source: Order, customer: CustomerProfile, override: str | None
    ) -> CustomerDeliverySite | None:
        """The site to deliver to: the client's choice, else the source order's, if it lives.

        A site that has been deactivated or deleted is treated as absent rather than
        reused, because the merchant deactivated it for a reason.
        """
        wanted = override or source.delivery_site_id
        if not wanted:
            return None
        return await self.session.scalar(
            select(CustomerDeliverySite).where(
                CustomerDeliverySite.id == wanted,
                CustomerDeliverySite.customer_id == customer.id,
                CustomerDeliverySite.is_active.is_(True),
            )
        )


def _retired_line(row: OrderItem) -> OrderLineRequest:
    """Carry a no-longer-known cylinder type through the plan so it can be reported.

    `model_construct` skips validation deliberately: the whole point is that this value is
    not a valid `CylinderType` any more, and it must survive long enough to be explained
    to the user rather than raising on the way in.
    """
    return OrderLineRequest.model_construct(cylinder_type=row.cylinder_type, quantity=row.quantity)
