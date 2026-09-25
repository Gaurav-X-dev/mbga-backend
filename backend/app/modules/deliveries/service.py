"""Delivery slip reads and writes (spec §10).

This is the module where four others meet, and every write here is the atomic join between them:

    order status  <->  slip status  <->  stock ledger  <->  notifications

A dispatch moves the order to OUT_FOR_DELIVERY, marks the slip DISPATCHED, takes filled
cylinders off the shelf, and tells the customer - **in one transaction**. Any of those four
happening without the others is a real-world inconsistency somebody has to unpick by hand: stock
that left with no delivery behind it, a customer told their order is coming when it is still in
the godown, an order stuck OUT_FOR_DELIVERY for a van that never loaded.

Order of operations is therefore the same everywhere: check everything that can refuse, then
write everything, then commit once. Spec §10.3 spells this out for the stock check - "no counts
change" if any line is short - and `StockLedger.dispatch` enforces it across lines.

Only merchant staff reach these routes. A customer follows their order through the order
endpoints; the slip is the godown's document, and it carries the crew's names and the vehicle.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi import status as http_status
from sqlalchemy import Select, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.customers.business_schemas import Address
from app.modules.customers.models import CustomerProfile
from app.modules.deliveries import codes, validation
from app.modules.deliveries.constants import (
    ALL_STATUSES,
    MAX_CODE_ATTEMPTS,
    STATUS_RANK,
    ConfirmationMethod,
    DeliveryStatus,
)
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.deliveries.numbering import SlipNumberAllocator
from app.modules.deliveries.schemas import (
    ConfirmDeliveryRequest,
    CreateDeliverySlipRequest,
    DeliveryItemResponse,
    DeliverySlipResponse,
    FailDeliveryRequest,
)
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.inventory.ledger import StockLedger
from app.modules.notifications.events import deliveries as delivery_events
from app.modules.orders import transitions
from app.modules.orders.constants import ORDER_LABELS, OrderStatus
from app.modules.orders.models import Order, OrderItem
from app.modules.pricing.constants import CylinderType
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.outbox import NotificationOutboxWriter


def _not_found() -> ApiError:
    """A slip outside the actor's merchant is not found, never forbidden.

    Slip numbers are sequential and guessable by design, so a 403 would confirm that another
    merchant has a slip at that id.
    """
    return ApiError("DELIVERY_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class SlipFilters:
    """Spec §10.1's query: one status or `ALL`, and a free-text search."""

    status: str | None = None
    search: str | None = None


class DeliveryService:
    def __init__(self, session: AsyncSession, actor: BusinessActor, settings: Settings) -> None:
        self.session = session
        self.actor = actor
        self.settings = settings
        self.merchant_id = actor.require_merchant_id()
        self.notifications = NotificationOutboxWriter(session)

    # --- Reads ------------------------------------------------------------------------------

    async def list_slips(self, filters: SlipFilters) -> list[DeliverySlipResponse]:
        """The Delivery & Dispatch list (spec §10.1).

        Ordered as a work queue rather than a log: what is on the road first, then what has to
        go out, then what went wrong, and delivered slips last because they need nobody. The
        rank is pushed into SQL as a CASE so the ordering survives the row limit - sorting in
        Python after a LIMIT would order whichever arbitrary page came back.
        """
        rank = case(STATUS_RANK, value=DeliverySlip.status, else_=len(STATUS_RANK))
        statement = self._scope(select(DeliverySlip)).order_by(
            rank.asc(),
            DeliverySlip.scheduled_date.desc(),
            # MySQL DATETIME has no fractional seconds, so same-day slips need a stable
            # tie-break or the list reshuffles between refreshes.
            DeliverySlip.slip_number.desc(),
        )
        statement = self._apply_status(statement, filters.status)
        statement = self._apply_search(statement, filters.search)
        slips = list(await self.session.scalars(statement))
        return [await self._view(slip) for slip in slips]

    async def get(self, slip_id: str) -> DeliverySlipResponse:
        return await self._view(await self._owned(slip_id))

    # --- Raising a slip ---------------------------------------------------------------------

    async def create(self, payload: CreateDeliverySlipRequest) -> DeliverySlipResponse:
        """Raise a slip against a confirmed order (an addition - see the schema's docstring).

        Nothing leaves the godown here and no stock moves: this is the loading instruction. The
        stock check happens at dispatch, deliberately, because a slip is often raised the evening
        before and the refill truck comes in the morning.
        """
        order = await self._slippable_order(payload.order_id)
        driver = await self._crew_member(payload.driver_user_id, role="driver")
        helper = await self._crew_member(payload.helper_user_id, role="helper")
        driver_name = validation.resolve_driver_name(
            payload, await self._account_name(driver, payload.driver_user_id)
        )
        method = validation.check_confirmation_method(payload.confirmation_method)
        vehicle = validation.check_vehicle_number(payload.vehicle_number)

        now = datetime.now(UTC)
        items = await self._order_items(order.id)
        slip = DeliverySlip(
            id=str(uuid4()),
            slip_number=await SlipNumberAllocator(self.session, self.merchant_id).allocate(),
            merchant_id=self.merchant_id,
            order_id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=order.customer_name,
            customer_mobile=await self._customer_mobile(order.customer_id),
            delivery_site_name=order.delivery_site_name,
            address_line1=order.address_line1,
            address_line2=order.address_line2,
            address_city=order.address_city,
            address_state=order.address_state,
            address_pincode=order.address_pincode,
            # Copied verbatim from the order so the slip and the order read identically.
            items_summary=order.items_summary,
            cylinders_allocated=order.total_cylinders,
            vehicle_number=vehicle,
            driver_user_id=payload.driver_user_id,
            driver_name=driver_name,
            helper_user_id=payload.helper_user_id,
            helper_name=validation.resolve_helper_name(
                payload, await self._account_name(helper, payload.helper_user_id)
            ),
            scheduled_date=_scheduled(payload.scheduled_date, order),
            empties_collected=0,
            confirmation_method=method.value,
            # Minted at dispatch, not here: a slip raised the evening before should not carry a
            # live code all night, and the code is only useful once the van is moving.
            confirmation_code_hash=None,
            confirmation_attempts=0,
            status=DeliveryStatus.SCHEDULED.value,
            created_by_name=self.actor.display_name,
            created_by_user_id=self.actor.user_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(slip)
        # Flushed before the lines: they are linked by a foreign key but by no ORM relationship,
        # so the unit of work does not order the inserts for us.
        await self.session.flush()
        for position, item in enumerate(items):
            self.session.add(
                DeliverySlipItem(
                    slip_id=slip.id,
                    cylinder_type=item.cylinder_type,
                    quantity=item.quantity,
                    position=position,
                )
            )
        # The order now points at its slip, which is what the order detail screen reads. Its
        # **status does not move**: raising a slip is planning, and nothing has physically
        # happened until the van is dispatched. The order stays CONFIRMED until then, and goes
        # straight to OUT_FOR_DELIVERY when it does.
        order.delivery_slip_id = slip.id
        order.updated_at = now
        self._notify_assignment(slip)
        await self.session.commit()
        return await self._view(slip)

    # --- Dispatch ---------------------------------------------------------------------------

    async def dispatch(self, slip_id: str) -> DeliverySlipResponse:
        """Mark a slip dispatched (spec §10.3). Atomic across all four systems.

        The stock check runs before anything is written, and `StockLedger.dispatch` refuses the
        whole load if any line is short - so a van that cannot be filled completely leaves the
        counts, the slip, the order and the customer exactly as they were.
        """
        slip = await self._owned(slip_id)
        self._require_status(slip, DeliveryStatus.DISPATCHED, ready=DeliveryStatus.SCHEDULED)
        order = await self._order_of(slip)
        now = datetime.now(UTC)

        # Refuses with spec §10.3's message, and touches no count if any line is short.
        await StockLedger(self.session, self.merchant_id).dispatch(
            await self._lines(slip.id),
            reference_id=slip.id,
            recorded_by_user_id=self.actor.user_id,
            recorded_by_name=self.actor.display_name,
            now=now,
        )

        # The code the customer will read out at the gate. Minted here, told to them in the
        # notification below, and kept only as a hash.
        code = codes.generate() if slip.confirmation_method == ConfirmationMethod.OTP.value else None
        slip.status = DeliveryStatus.DISPATCHED.value
        slip.dispatched_at = now
        slip.dispatched_by_name = self.actor.display_name
        slip.confirmation_code_hash = codes.fingerprint(code) if code else None
        slip.confirmation_attempts = 0
        slip.updated_at = now
        transitions.advance(
            self.session,
            order,
            OrderStatus.OUT_FOR_DELIVERY,
            by_name=self.actor.display_name,
            by_user_id=self.actor.user_id,
            # Spec §10.3's wording, verbatim: it is what a customer ringing up is read back.
            note=f"Vehicle {slip.vehicle_number} · {slip.driver_name}",
            now=now,
        )
        self.notifications.queue(
            delivery_events.out_for_delivery(
                slip.customer_id,
                order.id,
                slip.order_number,
                driver_name=slip.driver_name,
                confirmation_code=code,
            )
        )
        await self.session.commit()
        return await self._view(slip, reveal_code=code)

    # --- Confirmation -----------------------------------------------------------------------

    async def confirm(self, slip_id: str, payload: ConfirmDeliveryRequest) -> DeliverySlipResponse:
        """Confirm a handover (spec §10.4).

        The code is checked before anything moves, and a wrong one costs an attempt and is
        committed on its own - so the count survives a client that retries in a loop, and the
        slip is not confirmed by the eleventh guess.
        """
        slip = await self._owned(slip_id)
        self._require_status(slip, DeliveryStatus.DELIVERED, ready=DeliveryStatus.DISPATCHED)
        collected = validation.check_empties(payload.empties_collected, slip.cylinders_allocated)
        await self._check_code(slip, payload.otp)

        order = await self._order_of(slip)
        now = datetime.now(UTC)
        slip.status = DeliveryStatus.DELIVERED.value
        slip.delivered_at = now
        slip.empties_collected = collected
        slip.confirmed_by_name = self.actor.display_name
        slip.note = validation.check_note(payload.note)
        # Spent. Keeping the hash would leave a code that still verifies against a slip that can
        # no longer be confirmed, which is a secret with no purpose.
        slip.confirmation_code_hash = None
        slip.updated_at = now

        if collected:
            lines = await self._lines(slip.id)
            await StockLedger(self.session, self.merchant_id).collect_empties(
                {_primary_type(lines): collected},
                reference_id=slip.id,
                recorded_by_user_id=self.actor.user_id,
                recorded_by_name=self.actor.display_name,
                now=now,
            )
        transitions.advance(
            self.session,
            order,
            OrderStatus.DELIVERED,
            by_name=self.actor.display_name,
            by_user_id=self.actor.user_id,
            note=_delivered_note(collected, slip.cylinders_allocated),
            now=now,
        )
        self.notifications.queue(
            delivery_events.delivered(
                slip.customer_id, order.id, slip.order_number, cylinders=slip.cylinders_allocated
            )
        )
        await self.session.commit()
        return await self._view(slip)

    # --- Failure ----------------------------------------------------------------------------

    async def fail(self, slip_id: str, payload: FailDeliveryRequest) -> DeliverySlipResponse:
        """Record a slip that did not deliver (an addition - see the schema's docstring).

        A dispatched slip that failed has stock sitting on a van. `returnedToStock` puts the
        filled cylinders back with a `CORRECTION`-free path: the cylinders physically returned,
        so the honest ledger entry is the reverse of the dispatch rather than an audit fudge.

        The order goes back to nothing automatically - it stays OUT_FOR_DELIVERY, because the
        transition table forbids reversing it and the office decides whether to reschedule or
        cancel. That is deliberate: silently walking an order backwards would lose the fact that
        it once went out.
        """
        slip = await self._owned(slip_id)
        if slip.status not in {DeliveryStatus.SCHEDULED.value, DeliveryStatus.DISPATCHED.value}:
            raise self._settled(slip)
        now = datetime.now(UTC)
        was_dispatched = slip.status == DeliveryStatus.DISPATCHED.value

        if was_dispatched and payload.returned_to_stock:
            # Back on the shelf. Booked as `EMPTIES_COLLECTED`'s counterpart - a receipt of
            # filled cylinders against this slip - so the ledger still reconciles to the counts.
            await StockLedger(self.session, self.merchant_id).return_filled(
                await self._lines(slip.id),
                reference_id=slip.id,
                recorded_by_user_id=self.actor.user_id,
                recorded_by_name=self.actor.display_name,
                now=now,
            )

        slip.status = DeliveryStatus.FAILED.value
        slip.failure_reason = payload.reason.strip()
        slip.confirmation_code_hash = None
        slip.updated_at = now
        self.notifications.queue(
            delivery_events.delivery_failed(
                self.merchant_id, slip.order_id, slip.order_number, reason=payload.reason.strip()
            )
        )
        if slip.driver_user_id:
            self.notifications.queue(
                delivery_events.unassigned_from_driver(
                    slip.driver_user_id, slip.id, slip.order_number, reason=payload.reason.strip()
                )
            )
        await self.session.commit()
        return await self._view(slip)

    # --- Guards -----------------------------------------------------------------------------

    def _require_status(
        self, slip: DeliverySlip, target: DeliveryStatus, *, ready: DeliveryStatus
    ) -> None:
        """Refuse with the reason the app shows, not a generic conflict.

        Spec §10.4 asks for two distinct messages - "already confirmed" and "not been dispatched
        yet" - because they call for opposite actions from whoever is holding the phone.
        """
        if slip.status == ready.value:
            return
        if slip.status == target.value:
            raise ApiError(
                "DELIVERY_ALREADY_SETTLED",
                http_status.HTTP_409_CONFLICT,
                f"Slip {slip.slip_number} has already been {target.value.lower()}.",
            )
        raise ApiError(
            "DELIVERY_NOT_READY",
            http_status.HTTP_409_CONFLICT,
            validation.not_ready_message(slip.slip_number, slip.status, ready),
        )

    def _settled(self, slip: DeliverySlip) -> ApiError:
        return ApiError(
            "DELIVERY_ALREADY_SETTLED",
            http_status.HTTP_409_CONFLICT,
            f"Slip {slip.slip_number} is {slip.status.lower()} and can no longer be changed.",
        )

    async def _check_code(self, slip: DeliverySlip, submitted: str | None) -> None:
        """Verify the proof-of-delivery code, spending one attempt on a wrong one."""
        if slip.confirmation_method != ConfirmationMethod.OTP.value:
            return
        if slip.confirmation_attempts >= MAX_CODE_ATTEMPTS:
            raise ApiError(
                "DELIVERY_CODE_LOCKED",
                http_status.HTTP_409_CONFLICT,
                "Too many incorrect codes for this delivery. Confirm it from the office.",
            )
        if not codes.is_well_formed(submitted):
            # Malformed, so nothing is hashed and no attempt is spent: a letter in the box is a
            # typo, not a guess.
            raise validation.bad_code()
        if codes.matches(
            submitted or "",
            slip.confirmation_code_hash,
            allow_mock=self.settings.dev_expose_otp_in_response,
        ):
            return
        slip.confirmation_attempts += 1
        # Committed on its own, because the caller's transaction is about to be abandoned by the
        # raise. Without this the attempt count resets on every retry and the budget is fiction.
        await self.session.commit()
        raise validation.bad_code()

    # --- Lookups ----------------------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
        """Every slip query starts here. Applied as a `WHERE`, never as a later filter."""
        return statement.where(DeliverySlip.merchant_id == self.merchant_id)

    async def _owned(self, slip_id: str) -> DeliverySlip:
        slip = await self.session.scalar(
            self._scope(select(DeliverySlip)).where(DeliverySlip.id == slip_id)
        )
        if slip is None:
            raise _not_found()
        return slip

    async def _slippable_order(self, order_id: str) -> Order:
        """The order this slip is for, and whether a van may be loaded for it.

        Another merchant's order is a 404, matching how `OrderService` reports one.
        """
        order = await self.session.scalar(
            select(Order).where(Order.id == order_id, Order.merchant_id == self.merchant_id)
        )
        if order is None:
            raise ApiError("ORDER_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)
        validation.check_order_state(order)
        existing = await self.session.scalar(
            self._scope(select(DeliverySlip)).where(
                DeliverySlip.order_id == order.id,
                DeliverySlip.status.in_(
                    [DeliveryStatus.SCHEDULED.value, DeliveryStatus.DISPATCHED.value]
                ),
            )
        )
        if existing is not None:
            raise ApiError(
                "DELIVERY_ALREADY_EXISTS",
                http_status.HTTP_409_CONFLICT,
                f"Order {order.order_number} is already on slip {existing.slip_number}.",
            )
        return order

    async def _order_of(self, slip: DeliverySlip) -> Order:
        order = await self.session.scalar(
            select(Order).where(Order.id == slip.order_id, Order.merchant_id == self.merchant_id)
        )
        if order is None:
            # The slip's own foreign key guarantees the row; if it is gone the data is broken and
            # a 404 on the slip is the honest answer rather than a 500.
            raise _not_found()
        return order

    async def _crew_member(self, user_id: str | None, *, role: str) -> DeliveryProfile | None:
        """A delivery profile of this merchant, active and approved, or a coded refusal.

        Checked rather than trusted: a slip naming a blocked driver, or one belonging to another
        merchant, would send that person a job they cannot open and leave the office believing
        it is assigned.
        """
        if not user_id:
            return None
        profile = await self.session.scalar(
            select(DeliveryProfile).where(
                DeliveryProfile.user_id == user_id,
                DeliveryProfile.merchant_id == self.merchant_id,
            )
        )
        return validation.check_crew(profile, role=role)

    async def _account_name(self, profile, user_id: str | None) -> str | None:
        """The crew member's real name, for the slip and for the customer's notification.

        One query, and only when a crew member was picked from the list - slip creation is not a
        list screen. Returns None for a hired van, which is what lets a typed name through.
        """
        if profile is None or not user_id:
            return None
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        return user.full_name or user.username or profile.employee_code

    async def _order_items(self, order_id: str) -> list[OrderItem]:
        return list(
            await self.session.scalars(
                select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.position)
            )
        )

    async def _lines(self, slip_id: str) -> dict[CylinderType, int]:
        """The slip's cylinders, as the ledger wants them."""
        rows = list(
            await self.session.scalars(
                select(DeliverySlipItem)
                .where(DeliverySlipItem.slip_id == slip_id)
                .order_by(DeliverySlipItem.position)
            )
        )
        return {CylinderType(row.cylinder_type): row.quantity for row in rows}

    async def _items_view(self, slip_id: str) -> list[DeliveryItemResponse]:
        rows = list(
            await self.session.scalars(
                select(DeliverySlipItem)
                .where(DeliverySlipItem.slip_id == slip_id)
                .order_by(DeliverySlipItem.position)
            )
        )
        return [
            DeliveryItemResponse(
                cylinder_type=CylinderType(row.cylinder_type),
                cylinder_label=_label(row.cylinder_type),
                quantity=row.quantity,
            )
            for row in rows
        ]

    async def _customer_mobile(self, customer_id: str) -> str | None:
        return await self.session.scalar(
            select(CustomerProfile.mobile_number).where(CustomerProfile.id == customer_id)
        )

    # --- Filters ----------------------------------------------------------------------------

    @staticmethod
    def _apply_status(statement: Select, value: str | None) -> Select:
        """`status = SCHEDULED | ... | ALL` (spec §10.1).

        An unrecognised value returns nothing rather than 422: it is a chip on a screen, and a
        stale chip should show an empty list, not an error dialog.
        """
        if not value or value.upper() == ALL_STATUSES:
            return statement
        return statement.where(DeliverySlip.status == value.upper())

    @staticmethod
    def _apply_search(statement: Select, value: str | None) -> Select:
        """Slip number, order number, customer name, vehicle number (spec §10.1).

        Also the customer's mobile, because that is what somebody holding a phone actually has
        when a customer rings to ask where their cylinders are.
        """
        term = (value or "").strip()
        if not term:
            return statement
        pattern = f"%{term}%"
        return statement.where(
            or_(
                DeliverySlip.slip_number.like(pattern),
                DeliverySlip.order_number.like(pattern),
                DeliverySlip.customer_name.like(pattern),
                DeliverySlip.vehicle_number.like(pattern),
                DeliverySlip.customer_mobile.like(pattern),
                DeliverySlip.driver_name.like(pattern),
            )
        )

    # --- Notifications ----------------------------------------------------------------------

    def _notify_assignment(self, slip: DeliverySlip) -> None:
        """Tell the driver the job is theirs.

        Only when the slip names a driver with an account: a hired van's driver has no phone to
        notify, and the office tells them directly. Keyed on the slip, so the same driver can be
        assigned many jobs without the events colliding on the outbox's uniqueness constraint.
        """
        if not slip.driver_user_id:
            return
        self.notifications.queue(
            delivery_events.assigned_to_driver(
                slip.driver_user_id,
                slip.id,
                slip.order_number,
                customer_name=slip.customer_name,
            )
        )

    # --- Views ------------------------------------------------------------------------------

    async def _view(self, slip: DeliverySlip, *, reveal_code: str | None = None) -> DeliverySlipResponse:
        return DeliverySlipResponse(
            id=slip.id,
            slip_number=slip.slip_number,
            order_id=slip.order_id,
            order_number=slip.order_number,
            customer_id=slip.customer_id,
            customer_name=slip.customer_name,
            delivery_address=Address(
                line1=slip.address_line1 or "",
                line2=slip.address_line2,
                city=slip.address_city or "",
                state=slip.address_state or "",
                pincode=slip.address_pincode or "",
            ),
            delivery_site_name=slip.delivery_site_name,
            items=await self._items_view(slip.id),
            items_summary=slip.items_summary,
            cylinders_allocated=slip.cylinders_allocated,
            vehicle_number=slip.vehicle_number,
            driver_name=slip.driver_name,
            helper_name=slip.helper_name,
            scheduled_date=slip.scheduled_date,
            dispatched_at=slip.dispatched_at,
            delivered_at=slip.delivered_at,
            empties_collected=slip.empties_collected,
            # Derived, so it cannot drift from the two numbers it is made of.
            pending_pickup=max(slip.cylinders_allocated - slip.empties_collected, 0),
            confirmation_method=ConfirmationMethod(slip.confirmation_method),
            status=DeliveryStatus(slip.status),
            failure_reason=slip.failure_reason,
            note=slip.note,
            dev_confirmation_code=(
                reveal_code if reveal_code and self.settings.dev_expose_otp_in_response else None
            ),
        )


def _label(cylinder_type: str) -> str:
    try:
        return ORDER_LABELS[CylinderType(cylinder_type)]
    except (KeyError, ValueError):
        return cylinder_type


def _scheduled(requested: date | None, order: Order) -> date:
    """The slip's date: what was asked for, or the day the cut-off already decided.

    Defaulting to the order's own `scheduled_delivery_date` means the common case needs no input
    and cannot contradict what the customer was promised at placement. A calendar day, not an
    instant - a van goes out on a date, and there is no delivery slot to carry a time.
    """
    return requested if requested is not None else order.scheduled_delivery_date


def _primary_type(lines: dict[CylinderType, int]) -> CylinderType:
    """Which cylinder the returned empties are booked against.

    Empties come back as bare cylinders and the driver is not asked to split them by type, so
    they are booked against the largest line on the slip - the one they almost certainly are.
    Stated here rather than hidden in the caller because it is an approximation, and the person
    reconciling the empty bucket deserves to find it written down.
    """
    return max(lines, key=lambda cylinder: (lines[cylinder], cylinder.value))


def _delivered_note(collected: int, allocated: int) -> str:
    pending = max(allocated - collected, 0)
    if not pending:
        return f"{collected} empties collected"
    return f"{collected} of {allocated} empties collected · {pending} pending pickup"
