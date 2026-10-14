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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, CustomerActorDep
from app.modules.orders.models import Order
from app.modules.orders.schemas import (
    BulkAssignmentPreviewRequest,
    BulkAssignmentPreviewResponse,
    BulkConfirmRequest,
    BulkConfirmResponse,
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    CutoffResponse,
    GroupedBulkConfirmRequest,
    OrderCylinderTypeResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    OrderResponse,
    OrderStatusMetaResponse,
    ReorderPreviewResponse,
    ReorderRequest,
    RepeatOrderRequest,
)
from app.modules.orders.service import OrderFilters, OrderService
from app.modules.vehicles.coverage import available_for_pincode
from app.modules.vehicles.schemas import AvailableVehicleResponse
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

OrderIdPath = Annotated[str, Path(alias="orderId", max_length=36)]


def build_order_router(channel: LoginChannel) -> APIRouter:
    """Build the `/orders` routes for one channel."""
    is_customer = channel is LoginChannel.CUSTOMER
    is_admin = channel is LoginChannel.ADMIN
    router = APIRouter(prefix="/orders", tags=[f"{channel.value.title()} Orders"])

    channel_only = Depends(require_login_channel(channel))
    actor_dependency = (
        CustomerActorDep if is_customer else AdminMerchantActorDep if is_admin else ActorDep
    )
    staff_guards = [channel_only]
    if is_admin:
        staff_guards.append(Depends(require_permission("merchants.view")))

    # A customer is authorised by owning the row, not by holding a permission (spec §2.1:
    # "Customers have permissions: []; their access is implied by ownership").
    read_guards = (
        [channel_only]
        if is_customer
        else [*staff_guards, Depends(require_permission("orders.view"))]
    )
    write_guards = (
        [channel_only]
        if is_customer
        else [*staff_guards, Depends(require_permission("orders.create"))]
    )

    # FastAPI caches `get_db_session` per request, so the actor dependency and the service
    # share one session and therefore one transaction.
    def build_service(
        actor: actor_dependency,
        session: Annotated[AsyncSession, Depends(get_db_session)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> OrderService:
        return OrderService(session, actor, settings)

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
        """When an order placed right now would be delivered, against the configured IST cut-off."""
        return await service.cutoff()

    @router.get(
        "/cylinder-types",
        response_model=list[OrderCylinderTypeResponse],
        dependencies=read_guards,
        responses=error_responses(401, 403, 404, 422),
        summary="Cylinder types available to a customer",
    )
    async def order_cylinder_types(
        service: ServiceDep,
        customer_id: Annotated[str | None, Query(alias="customerId")] = None,
    ) -> list[OrderCylinderTypeResponse]:
        return await service.cylinder_types(customer_id)

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
            Header(
                alias="Idempotency-Key",
                description="Optional. Retrying with the same key returns the first order rather than placing a second.",
            ),
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
        customer_id: Annotated[
            str | None,
            Query(
                alias="customerId",
                description="Staff filter; ignored for a customer, who only ever sees their own.",
            ),
        ] = None,
        order_status: Annotated[
            str | None,
            Query(
                alias="status",
                description="A status code, `ALL`, or `ACTIVE` for every non-terminal status.",
            ),
        ] = None,
        search: Annotated[
            str | None,
            Query(
                max_length=120,
                description="Matches order number, customer name or the items summary.",
            ),
        ] = None,
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
            Query(
                alias="customerId",
                description="Required for staff. A customer's own app omits it - the session decides.",
            ),
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
            Header(
                alias="Idempotency-Key",
                description="Optional. Retrying with the same key returns the first repeat rather than placing a second.",
            ),
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

    if not is_customer:

        @router.get(
            "/{orderId}/available-vehicles",
            response_model=list[AvailableVehicleResponse],
            dependencies=read_guards,
            responses=error_responses(401, 403, 404, 409),
            summary="Vehicles eligible for this order's delivery pincode",
        )
        async def order_available_vehicles(
            order_id: OrderIdPath,
            actor: actor_dependency,
            session: Annotated[AsyncSession, Depends(get_db_session)],
        ) -> list[AvailableVehicleResponse]:
            merchant_id = actor.require_merchant_id()
            order = await session.scalar(
                select(Order).where(Order.id == order_id, Order.merchant_id == merchant_id)
            )
            if order is None:
                raise ApiError("ORDER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
            if not order.address_pincode:
                raise ApiError(
                    "ORDER_PINCODE_MISSING",
                    status.HTTP_409_CONFLICT,
                    "Order delivery address has no pincode.",
                )
            return await available_for_pincode(session, merchant_id, order.address_pincode)

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
            Header(
                alias="Idempotency-Key",
                description="Optional. Retrying with the same key returns the first repeat rather than placing a second.",
            ),
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

    if not is_customer:
        # Staff only, and not built through `write_guards`: confirming is an acceptance of the
        # order by the merchant, which is not something a customer can do to their own order.
        # These static two-segment routes must be registered before `/{orderId}/confirm`.
        @router.post(
            "/bulk-assignment/preview",
            response_model=BulkAssignmentPreviewResponse,
            dependencies=[*staff_guards, Depends(require_permission("orders.update"))],
            responses=error_responses(401, 403, 404, 409, 422),
            summary="Group selected orders by pincode and list eligible vehicles",
        )
        async def bulk_assignment_preview(
            service: ServiceDep, payload: BulkAssignmentPreviewRequest
        ) -> BulkAssignmentPreviewResponse:
            return await service.bulk_assignment_preview(payload)

        @router.post(
            "/bulk-assignment/confirm",
            response_model=BulkConfirmResponse,
            dependencies=[*staff_guards, Depends(require_permission("orders.update"))],
            responses=error_responses(401, 403, 404, 409, 422),
            summary="Confirm pincode-wise bulk assignment groups",
        )
        async def confirm_bulk_assignment_groups(
            service: ServiceDep, payload: GroupedBulkConfirmRequest
        ) -> BulkConfirmResponse:
            return await service.confirm_grouped(payload)

        @router.post(
            "/{orderId}/confirm",
            response_model=OrderResponse,
            dependencies=[*staff_guards, Depends(require_permission("orders.update"))],
            responses=error_responses(401, 403, 404, 409),
            summary="Confirm an order",
        )
        async def confirm_order(
            service: ServiceDep,
            order_id: OrderIdPath,
            payload: ConfirmOrderRequest,
        ) -> OrderResponse:
            """Accept a placed order, moving it to `CONFIRMED`, and say who delivers it.

            **Not one of the spec's six order endpoints**, and its absence was a hole: §6.1
            defines the status, both apps render it on the tracking timeline, and a delivery slip
            may only be raised against a confirmed order. Without this every order stayed
            `PLACED` and no van could be scheduled.

            `delivery` names the van and crew in the same call. A separate "Schedule Delivery"
            step is deliberately not exposed: a newly confirmed order cannot be left without a
            driver assignment.

            The customer is notified on confirmation, and the driver on assignment. A legacy
            `CONFIRMED` order without a slip may be assigned by retrying this endpoint.
            A cancelled order is refused with `409`.
            """
            return await service.confirm(order_id, payload)

        @router.post(
            "/confirm",
            response_model=BulkConfirmResponse,
            dependencies=[*staff_guards, Depends(require_permission("orders.update"))],
            responses=error_responses(401, 403, 404, 409, 422),
            summary="Confirm several orders onto one van",
        )
        async def confirm_orders(
            service: ServiceDep, payload: BulkConfirmRequest
        ) -> BulkConfirmResponse:
            """Confirm a whole round in one call.

            The office loads a van, not an order: six orders for one industrial estate go out
            together, and naming the same driver six times is six chances to pick the wrong one.

            All or nothing. One order that cannot be confirmed - already cancelled, or a driver
            taken since the screen loaded - refuses the whole call, because a partial success
            leaves the operator reading a list to work out which four of six actually went.
            """
            return await service.confirm_many(payload)

    @router.post(
        "/{orderId}/cancel",
        response_model=OrderResponse,
        dependencies=write_guards
        if is_customer
        else [*staff_guards, Depends(require_permission("orders.cancel"))],
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
