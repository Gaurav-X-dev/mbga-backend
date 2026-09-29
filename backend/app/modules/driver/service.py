"""The delivery app's reads and writes (API_REFERENCE §6-§10).

This module is a **driver-shaped view of the dispatch board**, not a second delivery system.
Every row it touches is the same `delivery_slips` row the office sees. There is no parallel
`deliveries` table, because a slip that exists twice is a slip that disagrees with itself the
first time one copy is updated and the other is not - and in a godown that shows up as
cylinders that are on a van according to one screen and on the shelf according to another.

Tenancy works differently here than on the merchant channel. A driver has no merchant of their
own: they are scoped to **the slips addressed to them**, by `driver_user_id`. Somebody else's
slip is a 404, never a 403, for the same reason it is on the board - slip ids are guessable, and
a 403 would confirm one exists.

The handover itself is not reimplemented. `verify_customer_otp` builds a `DeliveryService`
scoped to the slip's merchant and calls its `confirm`, so the stock ledger, the order transition
and the customer's notification all happen exactly as they do from the office. A driver
confirming a delivery and a manager confirming the same delivery must leave the database in the
same state; the only way to guarantee that is for them to run the same code.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import status as http_status
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.constants import ConfirmationMethod, DeliveryStatus
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.deliveries.schemas import ConfirmDeliveryRequest as SlipConfirmRequest
from app.modules.deliveries.service import DeliveryService
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.driver.constants import (
    ACTIONABLE_STATUSES,
    APP_STATUS,
    AT_LOCATION_RADIUS_METRES,
    STATUS_RANK,
    DriverDeliveryStatus,
)
from app.modules.driver.schemas import (
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponse,
    DeliveryItemResponse,
    DriverDeliveryResponse,
    DriverInventoryLine,
    DriverInventoryResponse,
    DriverProfileResponse,
    StartDeliveryRequest,
    StartDeliveryResponse,
    VerifyCustomerOtpResponse,
)
from app.modules.orders.constants import ORDER_LABELS
from app.modules.pricing.constants import CylinderType
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.geo.distance import haversine_metres


def _not_found() -> ApiError:
    """Another driver's slip is not found, never forbidden - ids are guessable."""
    return ApiError("DELIVERY_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class DeliveryFilters:
    """What the driver's list screens ask for."""

    #: `today` limits to slips scheduled for the current business day; `history` returns settled
    #: ones. Both are a filter on the same query rather than separate code paths.
    scheduled_on: Any = None
    settled_only: bool = False
    limit: int = 50


class DriverService:
    def __init__(self, session: AsyncSession, actor: BusinessActor, settings: Settings) -> None:
        self.session = session
        self.actor = actor
        self.settings = settings
        self.driver_user_id = actor.user_id

    # --- Reads ------------------------------------------------------------------------------

    async def list_deliveries(self, filters: DeliveryFilters) -> list[DriverDeliveryResponse]:
        """The driver's work queue.

        Ordered the way they have to work through it: what is on the van first, then what is
        still to load, then what is finished. The rank goes into SQL rather than being sorted
        afterwards, so it survives the row limit.
        """
        rank = case(STATUS_RANK, value=DeliverySlip.status, else_=len(STATUS_RANK))
        statement = self._scope(select(DeliverySlip)).order_by(
            rank.asc(), DeliverySlip.scheduled_date.desc(), DeliverySlip.slip_number.desc()
        )
        if filters.scheduled_on is not None:
            statement = statement.where(DeliverySlip.scheduled_date == filters.scheduled_on)
        if filters.settled_only:
            statement = statement.where(
                DeliverySlip.status.in_(
                    [DeliveryStatus.DELIVERED.value, DeliveryStatus.FAILED.value]
                )
            )
        statement = statement.limit(filters.limit)
        slips = list(await self.session.scalars(statement))
        return [await self._view(slip) for slip in slips]

    async def get_delivery(self, slip_id: str) -> DriverDeliveryResponse:
        return await self._view(await self._mine(slip_id))

    # --- The trip ---------------------------------------------------------------------------

    async def start(self, slip_id: str, payload: StartDeliveryRequest) -> StartDeliveryResponse:
        """Record that the driver has set off, and where from (§7.1).

        The distance is a display number and a nudge, never a gate. Where the site has no
        recorded coordinates - which is most of them, because nobody surveys a customer's godown
        to onboard them - the distance is null and `isAtLocation` is true. Refusing to let a
        driver work because the office never typed in a latitude would be the software's problem
        becoming the customer's.
        """
        slip = await self._mine(slip_id)
        self._require_actionable(slip)

        now = datetime.now(UTC)
        slip.driver_latitude = payload.latitude
        slip.driver_longitude = payload.longitude
        # Idempotent: pressing Start twice keeps the first departure time, which is the one that
        # matters, while refreshing the position.
        slip.started_at = slip.started_at or now
        slip.updated_at = now

        metres = self._distance_to_site(slip, payload)
        await self.session.commit()
        return StartDeliveryResponse(
            delivery_id=slip.id,
            is_at_location=metres is None or metres <= AT_LOCATION_RADIUS_METRES,
            distance_metres_from_destination=None if metres is None else round(metres, 1),
            status=DriverDeliveryStatus.IN_PROGRESS,
        )

    async def confirm_counts(
        self, slip_id: str, payload: ConfirmDeliveryRequest
    ) -> ConfirmDeliveryResponse:
        """Record what the driver counted, before the customer proves receipt (§7.2).

        This does **not** complete the delivery: no stock moves, the order does not advance and
        the customer is not told. It saves the counts so the confirmation screen survives the app
        being backgrounded between counting the cylinders and the customer finding their code.

        Partial deliveries are refused rather than quietly mis-counted. The stock ledger books
        the slip's whole load at handover, so accepting a smaller number here would take the full
        quantity off the shelf while the driver still had some on the van. That case needs the
        office - it ends as a failed slip and a new one.
        """
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        if payload.delivered_quantity != slip.cylinders_allocated:
            raise ApiError(
                "DELIVERY_PARTIAL_NOT_SUPPORTED",
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"This delivery is for {slip.cylinders_allocated} cylinders. "
                "For a part delivery, call the office - they will close this slip and raise a new one.",
            )
        if payload.empty_collected_quantity > slip.cylinders_allocated:
            raise ApiError(
                "DELIVERY_EMPTIES_EXCEED_LOAD",
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"You cannot collect more than {slip.cylinders_allocated} empties on this delivery.",
            )

        slip.empties_collected = payload.empty_collected_quantity
        slip.note = (payload.note or "").strip() or None
        slip.updated_at = datetime.now(UTC)
        await self.session.commit()

        return ConfirmDeliveryResponse(
            delivery_id=slip.id,
            customer_otp_required=slip.confirmation_method == ConfirmationMethod.OTP.value,
            delivered_quantity=payload.delivered_quantity,
            empty_collected_quantity=payload.empty_collected_quantity,
        )

    async def verify_customer_otp(self, slip_id: str, otp: str) -> VerifyCustomerOtpResponse:
        """Complete the handover with the customer's code (§7.3).

        The work is done by `DeliveryService.confirm` - the same method the office calls - with
        an actor scoped to this slip's merchant. Stock comes off the books, the order becomes
        DELIVERED and the customer is notified, identically either way. Reimplementing any of
        that here would be a second version of the most consequential write in the system.
        """
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        service = DeliveryService(self.session, self._merchant_actor(slip), self.settings)
        await service.confirm(
            slip.id,
            SlipConfirmRequest(
                otp=otp,
                empties_collected=slip.empties_collected,
                note=slip.note,
            ),
        )
        await self.session.refresh(slip)
        return VerifyCustomerOtpResponse(
            delivery_id=slip.id,
            order_number=slip.order_number,
            delivered_quantity=slip.cylinders_allocated,
            empty_collected_quantity=slip.empties_collected,
            completed_at=slip.delivered_at or datetime.now(UTC),
        )

    # --- Profile ----------------------------------------------------------------------------

    async def profile(self) -> DriverProfileResponse:
        user, delivery_profile = await self._account()
        name = user.full_name or "Driver"
        return DriverProfileResponse(
            id=user.id,
            name=name,
            phone=user.mobile_number or "",
            employee_code=delivery_profile.employee_code if delivery_profile else None,
            vehicle_number=delivery_profile.vehicle_number if delivery_profile else None,
            role=(delivery_profile.delivery_user_type if delivery_profile else "DRIVER").title(),
            on_duty=bool(delivery_profile.on_duty) if delivery_profile else False,
            avatar_initials=_initials(name),
        )

    async def set_duty(self, on_duty: bool) -> DriverProfileResponse:
        """Go on or off duty (§8.2).

        Going off duty is refused while a van of theirs is still out. Those cylinders are on the
        road under this driver's name, and letting them sign off would leave a dispatched slip
        with nobody responsible for it - the office would find out when the customer called.
        """
        _, delivery_profile = await self._account()
        profile = self._require_profile(delivery_profile)

        if not on_duty:
            outstanding = await self.session.scalar(
                select(func.count())
                .select_from(DeliverySlip)
                .where(
                    DeliverySlip.driver_user_id == self.driver_user_id,
                    DeliverySlip.status == DeliveryStatus.DISPATCHED.value,
                )
            )
            if outstanding:
                raise ApiError(
                    "DRIVER_HAS_ACTIVE_DELIVERIES",
                    http_status.HTTP_409_CONFLICT,
                    f"You still have {outstanding} delivery(s) out. "
                    "Complete them, or ask the office to close them, before going off duty.",
                )

        profile.on_duty = on_duty
        profile.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self.profile()

    # --- Van stock --------------------------------------------------------------------------

    async def inventory(self) -> DriverInventoryResponse:
        """What is on this driver's van (§10).

        Derived from their dispatched slips, never stored. The merchant's `stock_items` already
        holds the filled count and the dispatch check already subtracts what the vans are
        carrying; a third number kept in its own table would be the one that goes stale.

        Empties are what they have picked up on drops not yet closed - cylinders in their hands
        that the godown has not booked back in.
        """
        lines = (
            await self.session.execute(
                select(DeliverySlipItem.cylinder_type, func.sum(DeliverySlipItem.quantity))
                .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
                .where(
                    DeliverySlip.driver_user_id == self.driver_user_id,
                    DeliverySlip.status == DeliveryStatus.DISPATCHED.value,
                )
                .group_by(DeliverySlipItem.cylinder_type)
            )
        ).all()
        empties = await self.session.scalar(
            select(func.coalesce(func.sum(DeliverySlip.empties_collected), 0)).where(
                DeliverySlip.driver_user_id == self.driver_user_id,
                DeliverySlip.status == DeliveryStatus.DISPATCHED.value,
            )
        )
        active = await self.session.scalar(
            select(func.count())
            .select_from(DeliverySlip)
            .where(
                DeliverySlip.driver_user_id == self.driver_user_id,
                DeliverySlip.status == DeliveryStatus.DISPATCHED.value,
            )
        )
        return DriverInventoryResponse(
            full_cylinders=[
                DriverInventoryLine(
                    cylinder_type=cylinder_type,
                    label=_label(cylinder_type),
                    quantity=int(total or 0),
                )
                for cylinder_type, total in lines
            ],
            full_cylinder_count=sum(int(total or 0) for _, total in lines),
            empty_cylinder_count=int(empties or 0),
            active_deliveries=int(active or 0),
        )

    # --- Guards and lookups -----------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
        """Every query starts here: this driver's slips, nobody else's."""
        return statement.where(DeliverySlip.driver_user_id == self.driver_user_id)

    async def _mine(self, slip_id: str) -> DeliverySlip:
        slip = await self.session.scalar(
            self._scope(select(DeliverySlip)).where(DeliverySlip.id == slip_id)
        )
        if slip is None:
            raise _not_found()
        return slip

    def _require_actionable(self, slip: DeliverySlip) -> None:
        if slip.status not in ACTIONABLE_STATUSES:
            raise ApiError(
                "DELIVERY_ALREADY_SETTLED",
                http_status.HTTP_409_CONFLICT,
                f"Order {slip.order_number} is already {slip.status.lower()}.",
            )

    def _require_dispatched(self, slip: DeliverySlip) -> None:
        """Only a van that has actually left can hand anything over."""
        if slip.status == DeliveryStatus.DISPATCHED.value:
            return
        if slip.status == DeliveryStatus.SCHEDULED.value:
            raise ApiError(
                "DELIVERY_NOT_READY",
                http_status.HTTP_409_CONFLICT,
                f"Order {slip.order_number} has not been dispatched yet. "
                "Ask the office to release it before you deliver.",
            )
        raise ApiError(
            "DELIVERY_ALREADY_SETTLED",
            http_status.HTTP_409_CONFLICT,
            f"Order {slip.order_number} is already {slip.status.lower()}.",
        )

    def _require_profile(self, profile: DeliveryProfile | None) -> DeliveryProfile:
        if profile is None:
            raise ApiError(
                "DRIVER_PROFILE_NOT_FOUND",
                http_status.HTTP_404_NOT_FOUND,
                "This account has no delivery profile. Ask the office to set one up.",
            )
        return profile

    def _merchant_actor(self, slip: DeliverySlip) -> BusinessActor:
        """The driver, acting on the merchant whose slip this is.

        The driver has no merchant of their own - they are scoped by `driver_user_id`. Handing
        `DeliveryService` the slip's merchant is what lets the shared confirm path run, and it is
        safe precisely because the slip was already proven to be theirs by `_mine`.
        """
        return BusinessActor(
            user_id=self.actor.user_id,
            login_channel=self.actor.login_channel,
            display_name=self.actor.display_name,
            session_id=self.actor.session_id,
            merchant_id=slip.merchant_id,
        )

    async def _account(self) -> tuple[User, DeliveryProfile | None]:
        user = await self.session.get(User, self.driver_user_id)
        if user is None:
            raise ApiError("SESSION_REVOKED", http_status.HTTP_401_UNAUTHORIZED)
        profile = await self.session.scalar(
            select(DeliveryProfile).where(DeliveryProfile.user_id == self.driver_user_id)
        )
        return user, profile

    def _distance_to_site(
        self, slip: DeliverySlip, payload: StartDeliveryRequest
    ) -> float | None:
        """Metres to the gate, or None when nobody has recorded where the gate is.

        Read straight off the slip, which copied it when the van was loaded. Most slips carry
        nothing here: an order usually goes to the customer's registered address rather than a
        surveyed site. None means "cannot measure" - never "wrong place".
        """
        if slip.destination_latitude is None or slip.destination_longitude is None:
            return None
        return haversine_metres(
            payload.latitude,
            payload.longitude,
            slip.destination_latitude,
            slip.destination_longitude,
        )

    async def _items(self, slip_id: str) -> list[DeliveryItemResponse]:
        rows = await self.session.scalars(
            select(DeliverySlipItem)
            .where(DeliverySlipItem.slip_id == slip_id)
            .order_by(DeliverySlipItem.position.asc(), DeliverySlipItem.id.asc())
        )
        return [
            DeliveryItemResponse(
                cylinder_type=row.cylinder_type,
                label=_label(row.cylinder_type),
                quantity=row.quantity,
            )
            for row in rows
        ]

    async def _customer_phone(self, customer_id: str) -> str | None:
        return await self.session.scalar(
            select(CustomerProfile.mobile_number).where(CustomerProfile.id == customer_id)
        )

    async def _view(self, slip: DeliverySlip) -> DriverDeliveryResponse:
        status_value = APP_STATUS.get(slip.status, DriverDeliveryStatus.PENDING)
        # A dispatched slip the driver has already started reads as in progress. The slip has no
        # separate column for it: "started" is simply a departure time being present.
        if slip.status == DeliveryStatus.DISPATCHED.value and slip.started_at is not None:
            status_value = DriverDeliveryStatus.IN_PROGRESS
        distance = None
        return DriverDeliveryResponse(
            id=slip.id,
            order_number=slip.order_number,
            slip_number=slip.slip_number,
            customer_name=slip.customer_name,
            customer_phone=slip.customer_mobile or await self._customer_phone(slip.customer_id),
            address=_one_line(slip),
            delivery_site_name=slip.delivery_site_name,
            items=await self._items(slip.id),
            items_summary=slip.items_summary,
            cylinders_allocated=slip.cylinders_allocated,
            status=status_value,
            scheduled_date=slip.scheduled_date,
            distance_km=distance,
            started_at=slip.started_at,
            completed_at=slip.delivered_at,
            empties_collected=slip.empties_collected,
            requires_customer_otp=(
                slip.status == DeliveryStatus.DISPATCHED.value
                and slip.confirmation_method == ConfirmationMethod.OTP.value
            ),
        )


def _label(cylinder_type: str) -> str:
    try:
        return ORDER_LABELS[CylinderType(cylinder_type)]
    except (KeyError, ValueError):
        return cylinder_type


def _one_line(slip: DeliverySlip) -> str:
    """The address as one string the driver can read or paste into maps."""
    parts = [
        slip.address_line1,
        slip.address_line2,
        slip.address_city,
        slip.address_state,
        slip.address_pincode,
    ]
    return ", ".join(part.strip() for part in parts if part and part.strip())


def _initials(name: str) -> str | None:
    words = [word for word in name.strip().split() if word]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return None
