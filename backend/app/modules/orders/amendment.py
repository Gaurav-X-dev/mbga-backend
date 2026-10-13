"""Changing what is on an order after it has been confirmed.

A driver is at the gate with two 19 KG on the van and the customer asks for a third, or does
not want the second after all. Until now the order was fixed the moment it was confirmed: the
only way to sell the third cylinder was to place a second order, which the customer would
receive as a second bill with a second number for one visit - and the only way to drop the
second was to cancel the whole order and start again.

**Lines already on the order keep the price they were placed at.** That price is what the
customer agreed to and what the order has been quoting them since; re-pricing it at today's
rate because a different line was added would change a figure nobody touched.

**A line new to the order is priced from the order's own rate card**, not this month's. It is
the same rule `GET /{id}/available-cylinder-types` already prices the driver's sheet by, and
they have to agree: the sheet is the price the customer is told at the gate, and a bill that
quietly used a newer rate card would charge them something else. A customer-specific override
still wins, the same as at placement.

**The order is re-totalled, never re-invoiced.** The bill is raised at handover, so an
amendment before the customer's code is read out simply changes what will be billed. After
that the invoice exists and this refuses - a printed bill is not edited.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status as http_status
from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from app.modules.orders.constants import ORDER_LABELS
from app.modules.orders.models import Order, OrderItem
from app.modules.pricing.constants import CylinderType, PricingTier, cylinders_for
from app.modules.pricing.service import resolve_customer_price, tier_prices_for_month
from app.shared.exceptions.api_error import ApiError
from app.shared.money.gst import order_total

#: A basket this long is a mistake rather than a sale, and the slip has to fit on a phone.
MAX_LINES = 12
#: Per type, matching what order placement allows.
MAX_QUANTITY = 99


@dataclass(frozen=True)
class AmendedLine:
    cylinder_type: str
    quantity: int


def _invalid(message: str, field: str = "items") -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Some fields are missing or invalid.",
        fields=[{"field": field, "code": "items_invalid", "message": message}],
    )


def merge(lines: list[AmendedLine]) -> list[tuple[str, int]]:
    """One row per cylinder type, in the order the app sent them.

    A zero drops the line: that is the app's way of saying the customer changed their mind,
    and it is clearer than a separate delete call for a line that may never have existed.
    """
    merged: dict[str, int] = {}
    for line in lines:
        if line.quantity < 0 or line.quantity > MAX_QUANTITY:
            raise _invalid(f"Quantity must be between 0 and {MAX_QUANTITY}.")
        merged[line.cylinder_type] = merged.get(line.cylinder_type, 0) + line.quantity
    kept = [(kind, qty) for kind, qty in merged.items() if qty > 0]
    if not kept:
        raise _invalid("An order needs at least one cylinder. Cancel it instead.")
    if len(kept) > MAX_LINES:
        raise _invalid(f"An order cannot have more than {MAX_LINES} lines.")
    return kept


class OrderAmender:
    """Re-cuts an order's lines and re-totals it, keeping agreed prices agreed."""

    def __init__(self, session, merchant_id: str, merchant_code: str | None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.merchant_code = merchant_code

    async def amend(self, order: Order, lines: list[tuple[str, int]]) -> Order:
        """Replace the order's lines with `lines` and re-total it.

        The caller has already decided this order may change - that it is not delivered, not
        invoiced, and that whoever is asking is allowed to ask.
        """
        existing, priced = await self._project(order, lines)

        split = order_total([(unit, qty) for _k, qty, unit, _o in priced], order.gst_percent)

        for row in existing.values():
            await self.session.delete(row)
        await self.session.flush()
        for position, (kind, quantity, unit, overridden) in enumerate(priced):
            self.session.add(
                OrderItem(
                    order_id=order.id,
                    cylinder_type=kind,
                    quantity=quantity,
                    unit_price=unit,
                    line_total=unit * quantity,
                    price_overridden=overridden,
                    position=position,
                )
            )

        order.total_cylinders = sum(qty for _k, qty, _u, _o in priced)
        order.items_summary = summary(priced)[:255]
        order.total_amount = split.total_amount
        order.subtotal = split.subtotal
        order.gst_amount = split.gst_amount
        order.updated_at = datetime.now(UTC)
        await self.session.flush()
        return order

    async def projected_total(self, order: Order, lines: list[tuple[str, int]]) -> int:
        """Price an amendment without writing it, for pre-write policy checks."""
        _existing, priced = await self._project(order, lines)
        return order_total(
            [(unit, qty) for _kind, qty, unit, _overridden in priced],
            order.gst_percent,
        ).total_amount

    async def _project(
        self, order: Order, lines: list[tuple[str, int]]
    ) -> tuple[dict[str, OrderItem], list[tuple[str, int, int, bool]]]:
        existing = {
            row.cylinder_type: row
            for row in await self.session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
        }
        fresh = [kind for kind, _qty in lines if kind not in existing]
        quoted = await self._price(order, fresh)

        priced: list[tuple[str, int, int, bool]] = []
        for kind, quantity in lines:
            row = existing.get(kind)
            if row is not None:
                # Agreed at placement and left alone. Only the count moves.
                priced.append((kind, quantity, row.unit_price, row.price_overridden))
                continue
            unit, overridden = quoted[kind]
            priced.append((kind, quantity, unit, overridden))

        return existing, priced

    async def _price(self, order: Order, kinds: list[str]) -> dict[str, tuple[int, bool]]:
        """The order's own rate for the types it does not already carry.

        Priced off `order.pricing_month_id` rather than the current month, so the figure the
        driver was shown on the doorstep sheet is the figure that reaches the bill.
        """
        if not kinds:
            return {}
        try:
            wanted = [CylinderType(kind) for kind in kinds]
        except ValueError as exc:  # an unknown cylinder type
            raise _invalid(f"{exc.args[0]} is not a cylinder we sell.") from exc

        customer = await self.session.get(CustomerProfile, order.customer_id)
        customer_type = (
            (customer.customer_type if customer else None) or order.customer_type or "RETAIL"
        )
        allowed = set(cylinders_for(customer_type))
        for cylinder_type in wanted:
            # A retail customer cannot be sold a hippo at the gate any more than online.
            if cylinder_type not in allowed:
                raise _invalid(
                    f"{cylinder_type.value} is not sold to a {customer_type.lower()} customer.",
                )

        if not order.pricing_month_id:
            raise ApiError(
                "PRICING_NOT_CONFIGURED",
                http_status.HTTP_409_CONFLICT,
                "This order has no pricing month, so its doorstep prices cannot be resolved.",
            )
        tier = (customer.pricing_tier if customer else None) or PricingTier.STANDARD.value
        tier_prices = await tier_prices_for_month(self.session, order.pricing_month_id, tier)
        if not tier_prices and tier != PricingTier.STANDARD.value:
            tier_prices = await tier_prices_for_month(
                self.session, order.pricing_month_id, PricingTier.STANDARD.value
            )

        priced: dict[str, tuple[int, bool]] = {}
        for cylinder_type in wanted:
            tier_price = tier_prices.get(cylinder_type.value)
            resolved = await resolve_customer_price(
                self.session, order.customer_id, cylinder_type.value, tier_price
            )
            if resolved is None or int(resolved) <= 0:
                raise ApiError(
                    "CYLINDER_PRICE_NOT_CONFIGURED",
                    http_status.HTTP_409_CONFLICT,
                    f"Price is not configured for {cylinder_type.value}.",
                )
            priced[cylinder_type.value] = (
                int(resolved),
                tier_price is None or resolved != tier_price,
            )
        return priced


def summary(priced: list[tuple[str, int, int, bool]]) -> str:
    """`'2 x 19 KG Cylinder, 1 x 5 KG Cylinder'`, as the order list and the slip print it."""
    return ", ".join(
        f"{quantity} x {ORDER_LABELS.get(CylinderType(kind), kind)}"
        for kind, quantity, _unit, _overridden in priced
    )
