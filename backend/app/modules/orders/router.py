"""Order routes, mounted on the customer and merchant channels (spec §6).

Both channels mount the *same* handlers through `build_order_router`, the way
`build_document_router` already does. Only two things differ, and they are the two that
genuinely do: which actor dependency resolves the caller, and whether a permission is
required. A customer needs none - ownership is the rule, and `OrderService._scope()`
enforces it - while staff need `orders.view` to read and `orders.create` to place.

Routes stay channel-prefixed. An unprefixed `/orders` would be reachable with any channel's
token and would undo the isolation the auth layer provides.

Route order matters: `/orders/statuses`, `/orders/cutoff` and `/orders/quote` are declared
before `/orders/{order_id}`, or "statuses" would be matched as an order id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, CustomerActorDep
from app.modules.orders.schemas import (
    CancelOrderRequest,
    CreateOrderRequest,
    CutoffResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    OrderResponse,
    OrderStatusMetaResponse,
    ReorderPreviewResponse,
    ReorderRequest,
    RepeatOrderRequest,
)
from app.modules.orders.service import OrderFilters, OrderService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

OrderIdPath = Annotated[str, Path(alias="orderId", max_length=36)]


def build_order_router(channel: LoginChannel) -> APIRouter:
    """Build the `/orders` routes for one channel."""
    is_customer = channel is LoginChannel.CUSTOMER
    router = APIRouter(prefix="/orders", tags=[f"{channel.value.title()} Orders"])

    channel_only = Depends(require_login_channel(channel))
    actor_dependency = CustomerActorDep if is_customer else ActorDep

    # A customer is authorised by owning the row, not by holding a permission (spec §2.1:
    # "Customers have permissions: []; their access is implied by ownership").
    read_guards = [channel_only] if is_customer else [channel_only, Depends(require_permission("orders.view"))]
    write_guards = [channel_only] if is_customer else [channel_only, Depends(require_permission("orders.create"))]

    # FastAPI caches `get_db_session` per request, so the actor dependency and the service
    # share one session and therefore one transaction.
    def build_service(
        actor: actor_dependency,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> OrderService:
        return OrderService(session, actor)

    ServiceDep = Annotated[OrderService, Depends(build_service)]

    @router.get(
        "/statuses",
        response_model=list[OrderStatusMetaResponse],
        dependencies=read_guards,
        responses=error_responses(401, 403),
        summary="Order status catalogue",
    )
    async def order_statuses(service: ServiceDep) -> list[OrderStatusMetaResponse]:
        """Every status, sorted by `sequence`.

        The apps render their tracking timeline from this and hard-code no transitions, so
        adding a status here is all it takes for both apps to show it.
        """
        return service.statuses()

    @router.get(
        "/cutoff",
        response_model=CutoffResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403),
        summary="Order cut-off",
    )
    async def order_cutoff(service: ServiceDep) -> CutoffResponse:
        """When an order placed right now would be delivered (16:00 IST cut-off)."""
        return service.cutoff()

    @router.post(
        "/quote",
        response_model=OrderQuoteResponse,
        dependencies=write_guards,
        responses=error_responses(401, 403, 404, 409, 422),
        summary="Order quote",
    )
    async def order_quote(payload: OrderQuoteRequest, service: ServiceDep) -> OrderQuoteResponse:
        """Price a basket without placing it.

        Prices are GST-inclusive and resolved through the same helper the order and the
        invoice use, so the live summary a customer watches cannot disagree with what they
        are charged. Duplicate lines are merged before the quantity limits are applied.
        """
        return await service.quote(payload)

    @router.post(
        "",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=write_guards,
        responses=error_responses(401, 403, 404, 409, 422),
        summary="Create an order",
    )
    async def create_order(
        payload: CreateOrderRequest,
        service: ServiceDep,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", description="Optional. Retrying with the same key returns the first order rather than placing a second."),
        ] = None,
    ) -> OrderResponse:
        """Place an order (spec §6.4).

        Only an APPROVED, KYC-verified customer may have one placed, and an industrial
        order needs a delivery site. `source`, `createdBy` and the report period are
        derived from the session - none is read from the body.
        """
        return await service.create_with_idempotency(payload, idempotency_key)

    @router.get(
        "",
        response_model=list[OrderResponse],
        dependencies=read_guards,
        responses=error_responses(401, 403, 422),
        summary="Orders",
    )
    async def list_orders(
        service: ServiceDep,
        customer_id: Annotated[str | None, Query(alias="customerId", description="Staff filter; ignored for a customer, who only ever sees their own.")] = None,
        order_status: Annotated[str | None, Query(alias="status", description="A status code, `ALL`, or `ACTIVE` for every non-terminal status.")] = None,
        search: Annotated[str | None, Query(max_length=120, description="Matches order number, customer name or the items summary.")] = None,
    ) -> list[OrderResponse]:
        """Newest first. A customer sees only their own orders; staff see the merchant's."""
        return await service.list_orders(
            OrderFilters(customer_id=customer_id, status=order_status, search=search)
        )

    @router.get(
        "/repeat",
        response_model=ReorderPreviewResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404, 422),
        summary="Repeat last order (preview)",
    )
    async def repeat_preview(
        service: ServiceDep,
        customer_id: Annotated[
            str | None,
            Query(alias="customerId", description="Required for staff. A customer's own app omits it - the session decides."),
        ] = None,
    ) -> ReorderPreviewResponse:
        """The customer's last order, priced today, ready for a one-tap repeat.

        This is what the Repeat Order screen opens on: no order id, because the customer
        has not picked one - they want "the same as last time". The basket, the delivery
        site and the totals all come back filled in.

        "Last" is the most recent order that was not cancelled; if every order was
        cancelled, the newest of those is used rather than reporting no history.

        `404 NO_PREVIOUS_ORDER` when there is nothing to repeat yet.
        """
        return await service.repeat_preview(customer_id)

    @router.post(
        "/repeat",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=write_guards,
        responses=error_responses(401, 403, 404, 409, 422),
        summary="Repeat last order",
    )
    async def repeat_order(
        service: ServiceDep,
        payload: RepeatOrderRequest | None = None,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", description="Optional. Retrying with the same key returns the first repeat rather than placing a second."),
        ] = None,
    ) -> OrderResponse:
        """Place a repeat of the customer's last order, as `orderMode: REPEAT`.

        Staff send `customerId`; a customer's own app sends no body at all. Prices come
        from today's card and every rule is re-checked, so a repeat is never a shortcut
        past eligibility, quantity limits or the delivery-site requirement.
        """
        return await service.repeat(payload, idempotency_key)

    @router.get(
        "/{orderId}",
        response_model=OrderResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Order detail",
    )
    async def order_detail(service: ServiceDep, order_id: OrderIdPath) -> OrderResponse:
        """Someone else's order is reported as 404, never 403."""
        return await service.get(order_id)

    @router.get(
        "/{orderId}/reorder",
        response_model=ReorderPreviewResponse,
        dependencies=read_guards,
        responses=error_responses(401, 403, 404),
        summary="Reorder preview",
    )
    async def reorder_preview(service: ServiceDep, order_id: OrderIdPath) -> ReorderPreviewResponse:
        """What repeating this order would cost today, before anything is placed.

        A reorder is one tap, so the confirm sheet has to be able to say "₹200 more than
        last time" and "the Hippo is no longer available" *first*. Prices come from
        today's card, never from the old order.

        This never refuses: an ineligible customer or a dead delivery site comes back as
        `canReorder: false` with `blockedReason`, so the sheet can explain rather than
        having to translate a 403.
        """
        return await service.reorder_preview(order_id)

    @router.post(
        "/{orderId}/reorder",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=write_guards,
        responses=error_responses(401, 403, 404, 409, 422),
        summary="Reorder",
    )
    async def reorder(
        service: ServiceDep,
        order_id: OrderIdPath,
        payload: ReorderRequest | None = None,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", description="Optional. Retrying with the same key returns the first repeat rather than placing a second."),
        ] = None,
    ) -> OrderResponse:
        """Place a repeat of this order, as `orderMode: REPEAT`.

        Re-priced and re-validated as if it were a fresh order: the customer must still be
        eligible, the quantities must still be inside today's limits, and an industrial
        order still needs a live delivery site.

        A line that can no longer be repeated is a **409, not a silent drop** - receiving
        fewer cylinders than last time without being told is worse than being asked to
        adjust. Send `items` to place the adjusted basket.
        """
        return await service.reorder(order_id, payload, idempotency_key)

    @router.post(
        "/{orderId}/cancel",
        response_model=OrderResponse,
        dependencies=write_guards if is_customer else [channel_only, Depends(require_permission("orders.cancel"))],
        responses=error_responses(401, 403, 404, 409),
        summary="Cancel an order",
    )
    async def cancel_order(
        service: ServiceDep, order_id: OrderIdPath, payload: CancelOrderRequest | None = None
    ) -> OrderResponse:
        """Cancel an order that has not left the godown.

        **Not one of the spec's six order endpoints.** It is here because §6.1 defines a
        `CANCELLED` status and §2.1 grants an `orders.cancel` permission, and without a
        route nothing could ever reach that status. The transition table decides: once an
        order is OUT_FOR_DELIVERY it is a delivery failure, not a cancellation.
        """
        return await service.cancel(order_id, payload.reason if payload else None)

    return router
