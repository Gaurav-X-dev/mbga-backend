"""Order reads and writes (spec §6).

Two actors reach these routes and the difference between them is the whole access model:

* a **customer** may quote and order for themselves only, and sees only their own orders;
* **staff** act for any customer of their own merchant, and see that merchant's orders.

Both are resolved to the same `BusinessActor`, and `_scope()` turns that actor into the one
filter every query starts from. A row outside the actor's scope is reported as **404**,
never 403, so ids cannot be probed across tenants or across customers.

Nothing that identifies the actor is ever read from the body: `createdBy` comes from the
session, `source` is checked against the calling channel, and `status` is only ever moved by
a transition the catalogue allows.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.account_state import CUSTOMER_APPROVED
from app.modules.authentication.constants import LoginChannel
from app.modules.customers import eligibility as eligibility_policy
from app.modules.customers.business_schemas import Address
from app.modules.customers.constants import CustomerType, KycStatus
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.orders import reorder as reorder_rules
from app.modules.orders import validation
from app.modules.orders.constants import (
    ACTIVE_FILTER,
    ACTIVE_STATUSES,
    ALL_STATUSES,
    REGISTERED_ADDRESS_LABEL,
    STATUS_BY_CODE,
    STATUS_CATALOGUE,
    STATUS_TRANSITIONS,
    OrderMode,
    OrderSource,
    OrderStatus,
)
from app.modules.orders.cutoff import Cutoff, evaluate
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.orders.notifications import (
    order_cancelled,
    order_placed_customer,
    order_placed_merchant,
)
from app.modules.orders.numbering import OrderNumberAllocator
from app.modules.orders.quoting import Quote, QuoteEngine
from app.modules.orders.reorder import ReorderPlan, ReorderPlanner
from app.modules.orders.schemas import (
    CreateOrderRequest,
    CutoffResponse,
    OrderItemResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    OrderResponse,
    OrderStatusEntry,
    OrderStatusMetaResponse,
    ReorderPreviewResponse,
    ReorderRequest,
    RepeatOrderRequest,
    UnavailableLine,
)
from app.modules.pricing.constants import CylinderType
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.idempotency.service import IdempotencyService, validate_key
from app.shared.notifications.outbox import NotificationOutboxWriter

MAX_SEARCH_LENGTH = 120
#: Operation name the idempotency table keys order placements under.
IDEMPOTENT_CREATE = "orders.create"
#: Operation name repeat placements are keyed under, kept apart from a fresh create so a
#: reorder and a create with the same key cannot collide.
IDEMPOTENT_REORDER = "orders.reorder"


def _not_found() -> ApiError:
    return ApiError("ORDER_NOT_FOUND", status.HTTP_404_NOT_FOUND)


@dataclass(frozen=True)
class OrderFilters:
    customer_id: str | None = None
    status: str | None = None
    search: str | None = None


class OrderService:
    """Everything the order screens do, for one acting customer or staff member."""

    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()

    # --- Catalogue and cut-off ---------------------------------------------------------

    @staticmethod
    def statuses() -> list[OrderStatusMetaResponse]:
        """The status catalogue, sorted by sequence (spec §6.1)."""
        return [
            OrderStatusMetaResponse(
                code=meta.code,
                label=meta.label,
                sequence=meta.sequence,
                tone=meta.tone,
                description=meta.description,
                is_terminal=meta.is_terminal,
            )
            for meta in sorted(STATUS_CATALOGUE, key=lambda m: m.sequence)
        ]

    @staticmethod
    def cutoff() -> CutoffResponse:
        return _cutoff_view(evaluate())

    # --- Quote -------------------------------------------------------------------------

    async def quote(self, payload: OrderQuoteRequest) -> OrderQuoteResponse:
        """Price a basket without placing anything (spec §6.3)."""
        customer = await self._orderable_customer(payload.customer_id, require_approved=False)
        lines = validation.validate_basket(payload.items, customer_type=customer.customer_type)
        priced = await self._engine().price(customer.id, lines)
        return OrderQuoteResponse(
            items=[_line_view(line) for line in priced.lines],
            total_cylinders=priced.total_cylinders,
            total_amount=priced.total_amount,
            gst_percent=priced.gst_percent,
            subtotal=priced.subtotal,
            gst_amount=priced.gst_amount,
            cutoff=_cutoff_view(evaluate()),
        )

    # --- Create ------------------------------------------------------------------------

    async def create_with_idempotency(
        self,
        payload: CreateOrderRequest,
        idempotency_key: str | None,
        *,
        operation: str = IDEMPOTENT_CREATE,
    ) -> OrderResponse:
        """Place an order, honouring `Idempotency-Key` when the client sends one.

        Spec §1 asks `POST /orders` to accept the header, and the reason is concrete: a
        mobile client that times out mid-request and retries must not place a second order
        for the same basket. With no key this is a plain create - the header is optional,
        so a client that does not send one is not punished for it.

        On a replay the stored order id is re-read and rendered fresh rather than the old
        response body being replayed, so the caller sees the order's current status.
        """
        key = validate_key(idempotency_key)
        if key is None:
            return await self.create(payload)

        idempotency = IdempotencyService(self.session)
        record, replay = await idempotency.begin(
            actor=self.actor,
            operation=operation,
            key=key,
            payload=payload.model_dump(mode="json", by_alias=True),
        )
        if replay is not None:
            if replay.result_reference:
                return await self.get(replay.result_reference)
            # Completed without an id to re-read: nothing was actually placed, so the
            # retry is free to proceed rather than being told a phantom order exists.
            return await self.create(payload)

        try:
            order = await self.create(payload)
        except Exception as error:
            # The key is released as FAILED so a corrected retry is not blocked by the
            # attempt that was rejected. Committed on its own, because the order's
            # transaction has already rolled back.
            await idempotency.fail(record, failure_code=getattr(error, "code", "ERROR"))
            await self.session.commit()
            raise
        await idempotency.complete(record, response_status=201, result_reference=order.id)
        await self.session.commit()
        return order

    async def create(self, payload: CreateOrderRequest) -> OrderResponse:
        """Place an order (spec §6.4). One transaction.

        Order of operations matters: everything that can refuse the order runs before
        anything is written, so a rejected order burns no order number and leaves no
        half-built row behind.
        """
        customer = await self._orderable_customer(payload.customer_id, require_approved=True)
        lines = validation.validate_basket(payload.items, customer_type=customer.customer_type)
        site = await self._delivery_site(customer, payload.delivery_site_id)
        source = self._resolve_source(payload.source)

        priced = await self._engine().price(customer.id, lines)
        moment = evaluate()
        now = datetime.now(UTC)
        number = await OrderNumberAllocator(self.session, self.merchant_id).allocate()

        order = self._build(customer, site, priced, moment, source, payload.order_mode, number, now)
        self.session.add(order)
        await self.session.flush()

        for position, line in enumerate(priced.lines):
            self.session.add(
                OrderItem(
                    order_id=order.id,
                    cylinder_type=line.cylinder_type.value,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line.line_total,
                    price_overridden=line.overridden,
                    position=position,
                )
            )
        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                status=OrderStatus.PLACED.value,
                changed_by_name=self.actor.display_name,
                changed_by_user_id=self.actor.user_id,
                changed_at=now,
            )
        )

        # Queued on this transaction, so an order that rolls back cannot leave a
        # "Order placed" message behind (spec §18.8).
        outbox = NotificationOutboxWriter(self.session)
        outbox.queue(order_placed_customer(customer.id, order.id, order.order_number, order.total_amount))
        outbox.queue(order_placed_merchant(self.merchant_id, order.id, order.order_number, customer.name or ""))

        # Spec §6.4 side effect: the customer's last-order marker moves.
        customer.updated_at = now
        await self.session.commit()
        return await self._view(order)

    def _build(
        self,
        customer: CustomerProfile,
        site: CustomerDeliverySite | None,
        priced: Quote,
        moment: Cutoff,
        source: OrderSource,
        order_mode: OrderMode,
        number: str,
        now: datetime,
    ) -> Order:
        address = _site_address(site) if site else _customer_address(customer)
        staff_placed = source is OrderSource.MERCHANT_APP
        return Order(
            id=str(uuid4()),
            order_number=number,
            merchant_id=self.merchant_id,
            customer_id=customer.id,
            customer_name=customer.name or customer.owner_name or "Customer",
            customer_type=customer.customer_type or CustomerType.RETAIL.value,
            order_mode=order_mode.value,
            source=source.value,
            delivery_site_id=site.id if site else None,
            delivery_site_name=site.name if site else REGISTERED_ADDRESS_LABEL,
            address_line1=address.line1 or None,
            address_line2=address.line2,
            address_city=address.city or None,
            address_state=address.state or None,
            address_pincode=address.pincode or None,
            total_cylinders=priced.total_cylinders,
            items_summary=priced.items_summary[:255],
            total_amount=priced.total_amount,
            subtotal=priced.subtotal,
            gst_amount=priced.gst_amount,
            gst_percent=priced.gst_percent,
            pricing_month_id=priced.pricing_month_id,
            status=OrderStatus.PLACED.value,
            placed_at=now,
            cutoff_time=moment.cutoff_time,
            within_cutoff=moment.within_cutoff,
            scheduled_delivery_date=moment.scheduled_delivery_date,
            cutoff_message=moment.message,
            delivery_slot=moment.delivery_slot,
            # Only a staff placement names an actor; a customer ordering for themselves
            # leaves it null, and the app shows no "created by" line.
            created_by=self.actor.display_name if staff_placed else None,
            created_by_user_id=self.actor.user_id if staff_placed else None,
            created_at=now,
            updated_at=now,
        )

    # --- Reorder -------------------------------------------------------------------------

    async def reorder_preview(self, order_id: str) -> ReorderPreviewResponse:
        """What repeating **this** order would cost, without placing anything.

        Used by the "repeat this one" action in order history. The Repeat Order screen,
        which has no order in hand, calls `repeat_preview` instead - both share `_preview`
        below, so the two entry points cannot answer differently.
        """
        source = await self._owned(order_id)
        customer = await self.session.scalar(
            select(CustomerProfile).where(CustomerProfile.id == source.customer_id)
        )
        if customer is None:
            raise _not_found()
        return await self._preview(source, customer)

    async def _preview(self, source: Order, customer: CustomerProfile) -> ReorderPreviewResponse:
        """Price and check a repeat of `source` without writing anything.

        Deliberately does not raise for an ineligible customer: the sheet needs to *show*
        the reason, not receive a 403 it has to translate. `canReorder` and `blockedReason`
        carry that, and the POST is where the refusal actually happens.
        """
        plan = await ReorderPlanner(self.session).plan(source, customer)
        blocked = await self._eligibility_reason(customer)
        if plan.site_required_but_missing:
            blocked = blocked or reorder_rules.SITE_GONE

        priced = None
        if plan.items:
            lines = validation.merge_lines(plan.items)
            # Range-checked already by the planner, so anything left is priceable; a type
            # the card no longer carries surfaces as a dropped line rather than a 409.
            try:
                priced = await self._engine().price(customer.id, lines)
            except ApiError as error:
                if error.code != "CYLINDER_NOT_PRICED":
                    raise
                blocked = blocked or error.detail["message"]

        moment = evaluate()
        return ReorderPreviewResponse(
            source_order_id=source.id,
            source_order_number=source.order_number,
            source_order_status=source.status,
            source_placed_at=source.placed_at,
            source_items_summary=source.items_summary,
            items=[_line_view(line) for line in priced.lines] if priced else [],
            total_cylinders=priced.total_cylinders if priced else 0,
            total_amount=priced.total_amount if priced else 0,
            gst_percent=priced.gst_percent if priced else source.gst_percent,
            subtotal=priced.subtotal if priced else 0,
            gst_amount=priced.gst_amount if priced else 0,
            cutoff=_cutoff_view(moment),
            previous_total_amount=source.total_amount,
            price_changed=bool(priced) and priced.total_amount != source.total_amount,
            unavailable=[
                UnavailableLine(
                    cylinder_type=dropped.cylinder_type,
                    cylinder_label=dropped.label,
                    quantity=dropped.quantity,
                    reason=dropped.reason,
                )
                for dropped in plan.dropped
                if isinstance(dropped.cylinder_type, CylinderType)
            ],
            can_reorder=bool(priced) and plan.usable and blocked is None,
            blocked_reason=blocked,
            delivery_site_id=plan.site.id if plan.site else None,
            delivery_site_name=plan.site_name,
        )

    async def reorder(
        self, order_id: str, payload: ReorderRequest | None, idempotency_key: str | None
    ) -> OrderResponse:
        """Place a repeat of this order, priced and validated as if it were new.

        Routed through `create_with_idempotency` rather than duplicating the placement:
        the repeat is an ordinary order with `orderMode: REPEAT`, and giving it its own
        write path would be two implementations of the same rules.
        """
        source = await self._owned(order_id)
        customer = await self._orderable_customer(source.customer_id, require_approved=True)
        return await self._place_repeat(
            source,
            customer,
            payload.items if payload else None,
            payload.delivery_site_id if payload else None,
            idempotency_key,
        )

    async def _place_repeat(
        self,
        source: Order,
        customer: CustomerProfile,
        items: list | None,
        delivery_site_id: str | None,
        idempotency_key: str | None,
    ) -> OrderResponse:
        """Turn a plan into a placed order.

        Routed through `create_with_idempotency` rather than duplicating the placement: a
        repeat is an ordinary order with `orderMode: REPEAT`, and giving it its own write
        path would be two implementations of the same rules drifting apart.
        """
        plan = await ReorderPlanner(self.session).plan(
            source, customer, items=items, delivery_site_id=delivery_site_id
        )
        self._refuse_unusable(plan)
        return await self.create_with_idempotency(
            CreateOrderRequest(
                customerId=customer.id,
                items=plan.items,
                orderMode=OrderMode.REPEAT,
                deliverySiteId=plan.site.id if plan.site else None,
            ),
            idempotency_key,
            operation=IDEMPOTENT_REORDER,
        )

    @staticmethod
    def _refuse_unusable(plan: ReorderPlan) -> None:
        """Fail loudly rather than quietly placing a different order.

        Silently dropping a line would mean the customer taps "Reorder" and receives fewer
        cylinders than last time without being told. The preview has already explained
        each case, and `items` on the request is how the app sends the adjusted basket.
        """
        if plan.site_required_but_missing:
            raise validation.invalid("deliverySiteId", "site_required", reorder_rules.SITE_GONE)
        if plan.dropped:
            first = plan.dropped[0]
            raise ApiError(
                "REORDER_NOT_POSSIBLE",
                status.HTTP_409_CONFLICT,
                f"{first.label}: {first.reason}",
            )
        if not plan.items:
            raise validation.invalid("items", "items_required", validation.EMPTY_BASKET_MESSAGE)

    async def _eligibility_reason(self, customer: CustomerProfile) -> str | None:
        """The first reason this customer may not order, or None. Never raises."""
        sites = list(
            await self.session.scalars(
                select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == customer.id)
            )
        )
        outcome = eligibility_policy.evaluate(customer, sites)
        return None if outcome.eligible else outcome.reasons[0]

    # --- Repeat the last order -------------------------------------------------------------

    async def repeat_preview(self, customer_id: str | None) -> ReorderPreviewResponse:
        """The customer's last order, priced today, ready for a one-tap repeat.

        This is what the Repeat Order screen opens on: no order id, because the customer
        has not picked one - they tapped "order the same as last time".
        """
        customer = await self._repeat_customer(customer_id)
        source = await self._last_order(customer.id)
        return await self._preview(source, customer)

    async def repeat(
        self, payload: RepeatOrderRequest | None, idempotency_key: str | None
    ) -> OrderResponse:
        """Place a repeat of the customer's last order."""
        body = payload or RepeatOrderRequest()
        customer = await self._repeat_customer(body.customer_id, require_approved=True)
        source = await self._last_order(customer.id)
        return await self._place_repeat(
            source, customer, body.items, body.delivery_site_id, idempotency_key
        )

    async def _repeat_customer(
        self, customer_id: str | None, *, require_approved: bool = False
    ) -> CustomerProfile:
        """Whose last order this is about.

        A customer never names anyone: their session already says who they are, and an id
        they send is checked against it rather than trusted. Staff must name a customer,
        because they are not one.
        """
        if self.actor.is_customer:
            return await self._orderable_customer(
                customer_id or self.actor.require_customer_id(), require_approved=require_approved
            )
        if not customer_id:
            raise validation.invalid("customerId", "required", "Choose a customer.")
        return await self._orderable_customer(customer_id, require_approved=require_approved)

    async def _last_order(self, customer_id: str) -> Order:
        """The order a repeat is built from.

        The most recent order that was **not** cancelled, because "the same as last time"
        means the last one that actually stood. If every order was cancelled the newest of
        those is used instead - a customer who cancelled and wants to try again should not
        be told they have never ordered.
        """
        base = self._scope(select(Order)).where(Order.customer_id == customer_id)
        newest = base.order_by(Order.placed_at.desc(), Order.order_number.desc()).limit(1)

        source = await self.session.scalar(
            newest.where(Order.status != OrderStatus.CANCELLED.value)
        ) or await self.session.scalar(newest)
        if source is None:
            raise ApiError(
                "NO_PREVIOUS_ORDER",
                status.HTTP_404_NOT_FOUND,
                "There is no earlier order to repeat yet.",
            )
        return source

    # --- Read --------------------------------------------------------------------------

    async def list_orders(self, filters: OrderFilters) -> list[OrderResponse]:
        """Newest first (spec §6.5). A plain array - the apps do not paginate in Phase 1."""
        statement = self._scope(select(Order))
        statement = self._apply_filters(statement, filters)
        # Tie-broken on `order_number`, not on `id`. MySQL DATETIME keeps no fractional
        # seconds, so two orders placed in the same second have an identical `placed_at`,
        # and a uuid tiebreaker would order them at random - the list would reshuffle on
        # every refresh. The order number is monotonic per merchant and its YYMM prefix
        # keeps it lexically ordered across months too.
        orders = list(
            await self.session.scalars(
                statement.order_by(Order.placed_at.desc(), Order.order_number.desc())
            )
        )
        return await self._views(orders)

    async def get(self, order_id: str) -> OrderResponse:
        return await self._view(await self._owned(order_id))

    async def cancel(self, order_id: str, reason: str | None) -> OrderResponse:
        """Cancel an order that has not left the godown.

        Not one of the spec's six endpoints - see the route's docstring. The transition
        table is what decides, so this cannot cancel something already on the van.
        """
        order = await self._owned(order_id)
        allowed = STATUS_TRANSITIONS.get(order.status, frozenset())
        if OrderStatus.CANCELLED.value not in allowed:
            raise ApiError(
                "ORDER_NOT_CANCELLABLE",
                status.HTTP_409_CONFLICT,
                f"An order that is {STATUS_BY_CODE[order.status].label.lower()} can no longer be cancelled.",
            )
        now = datetime.now(UTC)
        order.status = OrderStatus.CANCELLED.value
        order.updated_at = now
        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                status=OrderStatus.CANCELLED.value,
                changed_by_name=self.actor.display_name,
                changed_by_user_id=self.actor.user_id,
                note=(reason or "").strip() or None,
                changed_at=now,
            )
        )
        NotificationOutboxWriter(self.session).queue(
            order_cancelled(order.customer_id, order.id, order.order_number)
        )
        await self.session.commit()
        return await self._view(order)

    # --- Scope and lookups ---------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
        """Narrow any order query to what this actor may see.

        Staff see their merchant's orders; a customer sees only their own. Applied as a
        `WHERE`, not as a check after loading, so a list can never leak a row it then
        filters out of the response.
        """
        statement = statement.where(Order.merchant_id == self.merchant_id)
        if self.actor.is_customer:
            return statement.where(Order.customer_id == self.actor.require_customer_id())
        return statement

    async def _owned(self, order_id: str) -> Order:
        order = await self.session.scalar(self._scope(select(Order)).where(Order.id == order_id))
        if order is None:
            raise _not_found()
        return order

    async def _orderable_customer(self, customer_id: str, *, require_approved: bool) -> CustomerProfile:
        """The customer this order is for, and whether they may have one placed.

        A customer may only ever name themselves. Staff may name any customer of their own
        merchant; anyone else's is a 404, not a 403.
        """
        if self.actor.is_customer and customer_id != self.actor.customer_id:
            raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)

        customer = await self.session.scalar(
            select(CustomerProfile).where(CustomerProfile.id == customer_id)
        )
        if customer is None or customer.merchant_id != self.merchant_id:
            raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        if require_approved:
            await self._require_eligible(customer)
        return customer

    async def _require_eligible(self, customer: CustomerProfile) -> None:
        """Spec §18.2, through the policy the eligibility endpoint already uses.

        Calling the shared policy rather than re-testing the two columns here is the point:
        the Create Order screen greys out its button from that same answer, so the form and
        the backend cannot disagree about who may order.
        """
        sites = list(
            await self.session.scalars(
                select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == customer.id)
            )
        )
        outcome = eligibility_policy.evaluate(customer, sites)
        if outcome.eligible:
            return
        code = (
            "ACCOUNT_PENDING_APPROVAL"
            if customer.status != CUSTOMER_APPROVED
            else "DOCUMENTS_PENDING_APPROVAL"
            if customer.kyc_status != KycStatus.VERIFIED.value
            else "ORDER_NOT_ALLOWED"
        )
        raise ApiError(code, status.HTTP_403_FORBIDDEN, outcome.reasons[0])

    async def _delivery_site(
        self, customer: CustomerProfile, site_id: str | None
    ) -> CustomerDeliverySite | None:
        """Resolve the delivery site, enforcing the industrial rule (spec §6.4, §18.2)."""
        industrial = (customer.customer_type or "").upper() == CustomerType.INDUSTRIAL.value
        if site_id:
            site = await self.session.scalar(
                select(CustomerDeliverySite).where(
                    CustomerDeliverySite.id == site_id,
                    CustomerDeliverySite.customer_id == customer.id,
                )
            )
            if site is None:
                # Another customer's site is not "forbidden", it simply is not one of this
                # customer's sites - which is what the app's picker offers.
                raise validation.invalid(
                    "deliverySiteId", "site_not_found", "Choose one of this customer's delivery sites."
                )
            return site
        if industrial:
            raise validation.invalid("deliverySiteId", "site_required", "Delivery site is required")
        return None

    def _resolve_source(self, claimed: OrderSource | None) -> OrderSource:
        """The channel decides the source; a body that disagrees is refused.

        Spec §1 says actor fields must never be trusted from the client, and `source` drives
        `createdBy`. Accepting a customer-app order that claims to be MERCHANT_APP would put
        a staff name on an order no staff member touched.
        """
        actual = (
            OrderSource.CUSTOMER_APP
            if self.actor.login_channel is LoginChannel.CUSTOMER
            else OrderSource.MERCHANT_APP
        )
        if claimed is not None and claimed is not actual:
            raise validation.invalid(
                "source", "source_mismatch", "This order source does not match the app you are signed in to."
            )
        return actual

    def _engine(self) -> QuoteEngine:
        return QuoteEngine(self.session, self.merchant_id, self.actor.merchant_code)

    def _apply_filters(self, statement: Select, filters: OrderFilters) -> Select:
        if filters.customer_id and not self.actor.is_customer:
            # Ignored for a customer: `_scope` has already pinned them to their own rows,
            # and honouring it here would let them ask about somebody else and get an
            # empty list instead of a 404.
            statement = statement.where(Order.customer_id == filters.customer_id)
        statement = self._apply_status(statement, filters.status)
        if filters.search:
            term = f"%{filters.search.strip()[:MAX_SEARCH_LENGTH]}%"
            statement = statement.where(
                or_(
                    Order.order_number.ilike(term),
                    Order.customer_name.ilike(term),
                    Order.items_summary.ilike(term),
                )
            )
        return statement

    @staticmethod
    def _apply_status(statement: Select, value: str | None) -> Select:
        if not value or not value.strip():
            return statement
        wanted = value.strip().upper()
        if wanted == ALL_STATUSES:
            return statement
        if wanted == ACTIVE_FILTER:
            return statement.where(Order.status.in_(ACTIVE_STATUSES))
        if wanted not in STATUS_BY_CODE:
            # An unknown status returns 422 rather than an empty list, which would read as
            # "no orders in this state" and hide a client-side typo.
            raise validation.invalid(
                "status",
                "status_unknown",
                f"Use one of {', '.join(STATUS_BY_CODE)}, ALL or ACTIVE.",
            )
        return statement.where(Order.status == wanted)

    # --- Views ---------------------------------------------------------------------------

    async def _view(self, order: Order) -> OrderResponse:
        return (await self._views([order]))[0]

    async def _views(self, orders: list[Order]) -> list[OrderResponse]:
        """Build every response in three queries rather than three per order."""
        if not orders:
            return []
        ids = [order.id for order in orders]

        items: dict[str, list[OrderItem]] = {order_id: [] for order_id in ids}
        for row in await self.session.scalars(
            select(OrderItem).where(OrderItem.order_id.in_(ids)).order_by(OrderItem.position, OrderItem.id)
        ):
            items[row.order_id].append(row)

        history: dict[str, list[OrderStatusHistory]] = {order_id: [] for order_id in ids}
        for row in await self.session.scalars(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id.in_(ids))
            .order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id)
        ):
            history[row.order_id].append(row)

        return [_order_view(order, items[order.id], history[order.id]) for order in orders]


# --- View builders ----------------------------------------------------------------------------


def _line_view(line) -> OrderItemResponse:
    return OrderItemResponse(
        cylinder_type=line.cylinder_type,
        cylinder_label=line.label,
        quantity=line.quantity,
        unit_price=line.unit_price,
        line_total=line.line_total,
    )


def _cutoff_view(moment: Cutoff) -> CutoffResponse:
    return CutoffResponse(
        cutoff_time=moment.cutoff_time,
        within_cutoff=moment.within_cutoff,
        scheduled_delivery_date=moment.scheduled_delivery_date,
        message=moment.message,
    )


def _customer_address(customer: CustomerProfile) -> Address:
    return Address(
        line1=customer.address_line1 or "",
        line2=customer.address_line2,
        city=customer.address_city or "",
        state=customer.address_state or "",
        pincode=customer.address_pincode or "",
    )


def _site_address(site: CustomerDeliverySite) -> Address:
    return Address(
        line1=site.address_line1,
        line2=site.address_line2,
        city=site.address_city,
        state=site.address_state,
        pincode=site.address_pincode,
    )


def _order_view(
    order: Order, items: list[OrderItem], history: list[OrderStatusHistory]
) -> OrderResponse:
    from app.modules.orders.constants import ORDER_LABELS
    return OrderResponse(
        id=order.id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        customer_type=order.customer_type,
        items=[
            OrderItemResponse(
                cylinder_type=item.cylinder_type,
                cylinder_label=ORDER_LABELS[CylinderType(item.cylinder_type)],
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in items
        ],
        total_cylinders=order.total_cylinders,
        items_summary=order.items_summary,
        order_mode=order.order_mode,
        source=order.source,
        delivery_site_id=order.delivery_site_id,
        delivery_site_name=order.delivery_site_name,
        delivery_address=Address(
            line1=order.address_line1 or "",
            line2=order.address_line2,
            city=order.address_city or "",
            state=order.address_state or "",
            pincode=order.address_pincode or "",
        ),
        subtotal=order.subtotal,
        gst_percent=order.gst_percent,
        gst_amount=order.gst_amount,
        total_amount=order.total_amount,
        status=order.status,
        status_history=[
            OrderStatusEntry(
                status=row.status, at=row.changed_at, by=row.changed_by_name, note=row.note
            )
            for row in history
        ],
        placed_at=order.placed_at,
        cutoff=CutoffResponse(
            cutoff_time=order.cutoff_time,
            within_cutoff=order.within_cutoff,
            scheduled_delivery_date=order.scheduled_delivery_date,
            message=order.cutoff_message,
        ),
        delivery_slot=order.delivery_slot,
        created_by=order.created_by,
        delivery_slip_id=order.delivery_slip_id,
        invoice_id=order.invoice_id,
    )
