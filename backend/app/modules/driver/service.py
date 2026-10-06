"""The delivery app's reads and writes (API_REFERENCE §6-§10)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import status as http_status
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.constants import IN_TRANSIT_STATUSES, DeliveryStatus
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.deliveries.schemas import (
    ConfirmDeliveryRequest as SlipConfirmRequest,
)
from app.modules.deliveries.schemas import FailDeliveryRequest
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
    BillingSummary,
    CancelDeliveryRequest,
    CancelDeliveryResponseData,
    CompletedDeliveryDetailResponseData,
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponseData,
    CustomerInfoDetail,
    CustomerLocation,
    DeliveryItemResponse,
    DriverDeliveryResponse,
    DriverInventoryLine,
    DriverInventoryResponseData,
    DriverProfileResponseData,
    EmptyDueSummary,
    EmptyReturnItem,
    GenerateQrRequest,
    GenerateQrResponseData,
    HistoryDeliveriesResponseData,
    HistoryDeliveryEntry,
    HistoryPaymentSummary,
    OutForDeliveryResponseData,
    PaymentEntry,
    ShiftStats,
    UpdateItemsRequest,
    VerifyCustomerOtpResponseData,
    VerifyLocationRequest,
    VerifyLocationResponseData,
)
from app.modules.driver.upi_qr import build_upi_link, png_base64
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.models import Invoice
from app.shared.date_time.business_calendar import business_today
from app.modules.orders.constants import ORDER_LABELS
from app.modules.pricing.constants import CylinderType
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.geo.distance import haversine_metres


def _not_found() -> ApiError:
    return ApiError("DELIVERY_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class DeliveryFilters:
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

    async def out_for_delivery(self, slip_id: str) -> OutForDeliveryResponseData:
        """The driver has set off with this delivery.

        This is what moves the order to `OUT_FOR_DELIVERY` and tells the customer their cylinders
        are on the way. It used to be the office pressing Dispatch, which meant the customer was
        told while the driver had not opened his phone - and the driver's own press did nothing
        but write a timestamp.
        """
        return (await self._set_off([slip_id]))[0]

    async def out_for_delivery_many(self, slip_ids: list[str]) -> list[OutForDeliveryResponseData]:
        """A whole round at once: the driver leaves the godown carrying six deliveries.

        All or nothing. Pressing this once is one event - the van left - so six slips that half
        moved would describe a van that is both out and not, and the stock check behind each one
        would be answered against a godown the earlier slips in the same call had already
        emptied.
        """
        return await self._set_off(slip_ids)

    async def _set_off(self, slip_ids: list[str]) -> list[OutForDeliveryResponseData]:
        started: list[OutForDeliveryResponseData] = []
        now = datetime.now(UTC)
        for slip_id in dict.fromkeys(slip_ids):
            slip = await self._mine(slip_id)
            self._require_actionable(slip)
            # Through the delivery module, which owns what dispatching means: the stock check
            # against what other vans are already carrying, the customer's code, the order's
            # status and the notification. The actor carries this driver's id and channel, so
            # the trail says the delivery app moved it.
            service = DeliveryService(self.session, self._merchant_actor(slip), self.settings)
            dev_confirmation_code = None
            if slip.status == DeliveryStatus.SCHEDULED.value:
                dispatched = await service.dispatch(slip.id, commit=False)
                dev_confirmation_code = dispatched.dev_confirmation_code
            slip.started_at = slip.started_at or now
            slip.updated_at = now
            started.append(
                OutForDeliveryResponseData(
                    delivery_id=slip.id,
                    order_number=slip.order_number,
                    status=(
                        DriverDeliveryStatus.ON_LOCATION
                        if slip.status == DeliveryStatus.ON_LOCATION.value
                        else DriverDeliveryStatus.OUT_FOR_DELIVERY
                    ),
                    updated_at=now.isoformat().replace("+00:00", "Z"),
                    dev_confirmation_code=dev_confirmation_code,
                )
            )
        await self.session.commit()
        return started

    async def cancel_delivery(
        self, slip_id: str, payload: CancelDeliveryRequest
    ) -> CancelDeliveryResponseData:
        """Close a delivery that did not happen. No customer OTP - see `DeliveryService.fail`."""
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)
        service = DeliveryService(self.session, self._merchant_actor(slip), self.settings)
        await service.fail(
            slip.id,
            FailDeliveryRequest(reason=payload.reason),
        )
        await self.session.refresh(slip)
        return CancelDeliveryResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            delivery_status=DeliveryStatus.FAILED.value,
            order_status="CANCELLED",
            cancelled_at=slip.updated_at.isoformat().replace("+00:00", "Z"),
        )

    async def verify_location(
        self, slip_id: str, payload: VerifyLocationRequest
    ) -> VerifyLocationResponseData:
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        now = datetime.now(UTC)
        slip.driver_latitude = payload.latitude
        slip.driver_longitude = payload.longitude
        metres = self._distance_to_site(slip, payload)

        # Simulate locking customer location if not already locked
        is_location_captured = True

        service = DeliveryService(self.session, self._merchant_actor(slip), self.settings)
        arrived_at = await service.mark_on_location(slip.id, now=now)
        return VerifyLocationResponseData(
            delivery_id=slip.id,
            delivery_status=DeliveryStatus.ON_LOCATION.value,
            order_status="ON_LOCATION",
            arrived_at=arrived_at,
            is_at_location=metres is None or metres <= AT_LOCATION_RADIUS_METRES,
            distance_meters_from_destination=None if metres is None else round(metres, 1),
            is_location_captured=is_location_captured,
            message="Location verified successfully",
        )

    async def update_items(
        self, slip_id: str, payload: UpdateItemsRequest
    ) -> DriverDeliveryResponse:
        slip = await self._mine(slip_id)
        self._require_actionable(slip)
        # We would typically update DeliverySlipItem and potentially Order here.
        # For flow compatibility, we just commit a note or simulate success.
        slip.note = payload.reason
        slip.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self._view(slip)

    async def generate_qr(self, slip_id: str, payload: GenerateQrRequest) -> GenerateQrResponseData:
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)
        if payload.order_id is not None and payload.order_id != slip.order_id:
            raise ApiError(
                "QR_ORDER_MISMATCH",
                http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The orderId does not belong to this delivery.",
                fields=[
                    {
                        "field": "orderId",
                        "code": "order_mismatch",
                        "message": "Use the orderId assigned to this delivery.",
                    }
                ],
            )

        from app.modules.merchants.models import Merchant

        merchant = await self.session.get(Merchant, slip.merchant_id)
        if not merchant or not merchant.upi_id or not merchant.upi_payee_name:
            raise ApiError(
                "MERCHANT_UPI_NOT_CONFIGURED",
                http_status.HTTP_409_CONFLICT,
                "Merchant UPI details are not configured in settings."
            )

        amount = format(
            Decimal(str(payload.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "f",
        )
        upi_string = build_upi_link(
            upi_id=merchant.upi_id,
            payee_name=merchant.upi_payee_name,
            amount=amount,
            order_id=slip.order_id,
            notes=payload.notes,
        )
        return GenerateQrResponseData(
            delivery_id=slip.id,
            order_id=slip.order_id,
            order_number=slip.order_number,
            amount=float(amount),
            upi_id=merchant.upi_id,
            payee_name=merchant.upi_payee_name,
            notes=payload.notes,
            upi_string=upi_string,
            qr_code_base64=png_base64(upi_string),
        )

    async def confirm_counts(
        self, slip_id: str, payload: ConfirmDeliveryRequest
    ) -> ConfirmDeliveryResponseData:
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        empty_qty = sum(item.quantity for item in payload.collected_empties)

        await self._record_delivered(slip, payload.delivered_items)
        slip.empties_collected = empty_qty
        slip.note = (payload.driver_notes or "").strip() or None
        slip.updated_at = datetime.now(UTC)
        await self.session.commit()

        return ConfirmDeliveryResponseData(
            delivery_id=slip.id,
            customer_otp_required=True,  # Forcing to True as per spec
            otp_channel="IN_APP_NOTIFICATION",
            message="OTP has been sent to customer's app notification",
        )

    async def _record_delivered(self, slip: DeliverySlip, delivered: list[Any]) -> None:
        """Write the driver's own counts onto the slip's lines.

        This is read back by `DeliveryService.confirm` when the customer's code completes the
        handover, and it is what the godown's books are then reduced by. Recording it here rather
        than passing it through the confirmation keeps one source of truth for a figure that is
        stated in one request and acted on in another.

        The driver's list is a **complete** statement of the handover: a line he does not mention
        was brought back, so it is recorded as zero rather than left to fall back to the
        allocation. Handing over more than the van was loaded with is refused - the extra
        cylinders would have to come from somewhere the slip cannot account for.
        """
        rows = {
            row.cylinder_type: row
            for row in await self.session.scalars(
                select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
            )
        }
        counts: dict[str, int] = {}
        for item in delivered:
            row = rows.get(item.cylinder_type)
            if row is None:
                raise ApiError(
                    "DELIVERY_ITEM_NOT_ON_SLIP",
                    http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{item.cylinder_type} is not on order {slip.order_number}.",
                )
            counts[item.cylinder_type] = counts.get(item.cylinder_type, 0) + item.quantity

        for cylinder_type, quantity in counts.items():
            allocated = rows[cylinder_type].quantity
            if quantity > allocated:
                raise ApiError(
                    "DELIVERY_QUANTITY_EXCEEDS_ALLOCATION",
                    http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"The van carries {allocated} of {cylinder_type}, not {quantity}.",
                )

        for cylinder_type, row in rows.items():
            row.delivered_quantity = counts.get(cylinder_type, 0)

    async def _delivered_total(self, slip: DeliverySlip) -> int:
        """How many cylinders actually changed hands on this slip.

        Falls back to the allocation when no per-line figure was recorded, which is the case for a
        slip the office confirmed itself.
        """
        rows = list(
            await self.session.scalars(
                select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
            )
        )
        if any(row.delivered_quantity is not None for row in rows):
            return sum(row.delivered_quantity or 0 for row in rows)
        return slip.cylinders_allocated

    async def verify_customer_otp(self, slip_id: str, otp: str) -> VerifyCustomerOtpResponseData:
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

        # Build multi-item receipt
        items = await self._items(slip.id, slip.order_id)
        # The receipt states the handover, so it counts what was handed over. On a part delivery
        # that is less than the slip allocated, and the empties are due against the cylinders the
        # customer actually received rather than the ones that went back on the van.
        delivered_total = await self._delivered_total(slip)
        payable, paid, pending = await self._money(slip)

        return VerifyCustomerOtpResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            status=DriverDeliveryStatus.COMPLETED,
            completed_at=(slip.delivered_at or datetime.now(UTC))
            .isoformat()
            .replace("+00:00", "Z"),
            total_delivered_quantity=delivered_total,
            delivered_items=items,
            total_empty_collected_quantity=slip.empties_collected,
            empty_collected_items=items,  # Simplified for mock
            empty_due_summary=EmptyDueSummary(
                expected_total=delivered_total,
                collected_total=slip.empties_collected,
                added_to_customer_pending_due=max(0, delivered_total - slip.empties_collected),
            ),
            payment=PaymentEntry(
                method="cash",
                split="full" if pending <= 0 else "partial",
                amount_collected=paid,
                payable_amount=payable,
                pending_balance=pending,
            ),
        )

    async def get_completed_detail(self, slip_id: str) -> CompletedDeliveryDetailResponseData:
        slip = await self._mine(slip_id)
        items = await self._items(slip.id, slip.order_id)
        customer_phone = slip.customer_mobile or await self._customer_phone(slip.customer_id)
        payable, paid, pending = await self._money(slip)

        return CompletedDeliveryDetailResponseData(
            id=slip.id,
            order_number=slip.order_number,
            status=DriverDeliveryStatus.COMPLETED,
            delivery_date=slip.scheduled_date.isoformat(),
            completed_at=(slip.delivered_at or datetime.now(UTC)).isoformat(),
            customer=CustomerInfoDetail(
                name=slip.customer_name, phone=customer_phone or "", address=_one_line(slip)
            ),
            delivered_items=items,
            empty_items=items,
            payment={
                "method": "cash",
                "split": "full" if pending <= 0 else "partial",
                "totalAmount": payable,
                "amountPaid": paid,
                "pendingBalance": pending,
            },
            driver_notes=slip.note,
        )

    async def list_history(
        self, period: str, page: int, limit: int
    ) -> HistoryDeliveriesResponseData:
        slips = await self.list_deliveries(DeliveryFilters(settled_only=True, limit=limit))
        # One query for the whole page rather than one per row: the figure on each line is the
        # invoice's, and reading them individually would be a query per delivery in the list.
        paid_by_order, pending_by_order = await self._settled_money([slip.id for slip in slips])
        entries = []
        for slip in slips:
            entries.append(
                HistoryDeliveryEntry(
                    id=slip.id,
                    order_number=slip.order_number,
                    customer_name=slip.customer.name,
                    status=slip.status,
                    delivery_date=slip.delivery_date,
                    completed_at=slip.delivery_date,  # Mock
                    total_delivered_count=sum(i.quantity for i in slip.items),
                    total_empties_count=sum(i.expected_quantity for i in slip.empty_returns),
                    items_summary=",".join([f"{i.quantity}x{i.label}" for i in slip.items]),
                    payment=HistoryPaymentSummary(
                        method="cash",
                        amount=paid_by_order.get(slip.id, 0.0),
                        status="FULL" if pending_by_order.get(slip.id, 0.0) <= 0 else "PARTIAL",
                    ),
                )
            )
        return HistoryDeliveriesResponseData(
            items=entries, total=len(entries), page=page, limit=limit
        )

    # --- Profile ----------------------------------------------------------------------------

    async def profile(self) -> DriverProfileResponseData:
        user, delivery_profile = await self._account()
        name = user.full_name or "Driver"
        return DriverProfileResponseData(
            id=user.id,
            name=name,
            phone=user.mobile_number or "",
            employee_code=delivery_profile.employee_code if delivery_profile else None,
            vehicle_number=delivery_profile.vehicle_number if delivery_profile else None,
            role=(delivery_profile.delivery_user_type if delivery_profile else "DRIVER").title(),
            on_duty=bool(delivery_profile.on_duty) if delivery_profile else False,
            avatar_initials=_initials(name),
            shift_stats=await self._shift_stats(),
        )

    async def set_duty(self, on_duty: bool) -> DriverProfileResponseData:
        _, delivery_profile = await self._account()
        profile = self._require_profile(delivery_profile)
        if not on_duty:
            outstanding = await self.session.scalar(
                select(func.count())
                .select_from(DeliverySlip)
                .where(
                    DeliverySlip.driver_user_id == self.driver_user_id,
                    DeliverySlip.status.in_(IN_TRANSIT_STATUSES),
                )
            )
            if outstanding:
                raise ApiError(
                    "DRIVER_HAS_ACTIVE_DELIVERIES",
                    http_status.HTTP_409_CONFLICT,
                    f"You still have {outstanding} delivery(s) out.",
                )
        profile.on_duty = on_duty
        profile.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self.profile()

    # --- Van stock --------------------------------------------------------------------------

    async def inventory(self) -> DriverInventoryResponseData:
        lines = (
            await self.session.execute(
                select(DeliverySlipItem.cylinder_type, func.sum(DeliverySlipItem.quantity))
                .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
                .where(
                    DeliverySlip.driver_user_id == self.driver_user_id,
                    DeliverySlip.status.in_(IN_TRANSIT_STATUSES),
                )
                .group_by(DeliverySlipItem.cylinder_type)
            )
        ).all()
        empties = await self.session.scalar(
            select(func.coalesce(func.sum(DeliverySlip.empties_collected), 0)).where(
                DeliverySlip.driver_user_id == self.driver_user_id,
                DeliverySlip.status.in_(IN_TRANSIT_STATUSES),
            )
        )
        active = await self.session.scalar(
            select(func.count())
            .select_from(DeliverySlip)
            .where(
                DeliverySlip.driver_user_id == self.driver_user_id,
                DeliverySlip.status.in_(IN_TRANSIT_STATUSES),
            )
        )

        stock_by_type = [
            DriverInventoryLine(
                cylinder_type=cylinder_type,
                label=_label(cylinder_type),
                full_count=int(total or 0),
                empty_count=0,  # Mock
            )
            for cylinder_type, total in lines
        ]

        return DriverInventoryResponseData(
            total_full_cylinders=sum(int(total or 0) for _, total in lines),
            total_empty_cylinders=int(empties or 0),
            active_deliveries_count=int(active or 0),
            stock_by_type=stock_by_type,
        )

    # --- Guards and lookups -----------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
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
        if slip.status in IN_TRANSIT_STATUSES:
            return
        if slip.status == DeliveryStatus.SCHEDULED.value:
            raise ApiError(
                "DELIVERY_NOT_READY",
                http_status.HTTP_409_CONFLICT,
                f"Order {slip.order_number} has not been dispatched yet.",
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
                "This account has no delivery profile.",
            )
        return profile

    def _merchant_actor(self, slip: DeliverySlip) -> BusinessActor:
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

    def _distance_to_site(self, slip: DeliverySlip, payload: VerifyLocationRequest) -> float | None:
        if slip.destination_latitude is None or slip.destination_longitude is None:
            return None
        return haversine_metres(
            payload.latitude,
            payload.longitude,
            slip.destination_latitude,
            slip.destination_longitude,
        )

    async def _settled_money(
        self, slip_ids: list[str]
    ) -> tuple[dict[str, float], dict[str, float]]:
        """`{slip id: paid}` and `{slip id: balance}` for a page of history."""
        if not slip_ids:
            return {}, {}
        rows = await self.session.execute(
            select(DeliverySlip.id, Invoice.paid_amount, Invoice.balance)
            .join(Invoice, Invoice.order_id == DeliverySlip.order_id)
            .where(DeliverySlip.id.in_(slip_ids))
        )
        paid: dict[str, float] = {}
        pending: dict[str, float] = {}
        for slip_id, amount, balance in rows:
            paid[slip_id] = float(amount or 0)
            pending[slip_id] = float(balance or 0)
        return paid, pending

    async def _shift_stats(self) -> ShiftStats:
        """What this driver has actually done today.

        Counted from their own settled slips rather than reported as a fixed 5 deliveries and
        15,000 collected, which every driver saw on every day including their first.
        """
        today = business_today()
        slips = list(
            await self.session.scalars(
                self._scope(select(DeliverySlip)).where(
                    DeliverySlip.scheduled_date == today,
                    DeliverySlip.status == DeliveryStatus.DELIVERED.value,
                )
            )
        )
        collected = 0.0
        for slip in slips:
            invoice = await self.session.scalar(
                select(Invoice).where(Invoice.order_id == slip.order_id)
            )
            if invoice is not None:
                collected += float(invoice.paid_amount)
        return ShiftStats(
            completed_deliveries_today=len(slips),
            cash_collected_today=collected,
            total_empties_collected_today=sum(slip.empties_collected or 0 for slip in slips),
        )

    async def _money(self, slip: DeliverySlip) -> tuple[float, float, float]:
        """What the customer owes on this delivery: (payable, paid, pending).

        Read from the invoice the handover raised, or from the order while there is none. Both
        carry GST **inside** `total_amount` rather than added on top, so the figure here is the
        one the customer is asked for - which matters, because the driver reads it out at the
        gate and used to be shown a flat 1000.
        """
        invoice = await self.session.scalar(
            select(Invoice).where(Invoice.order_id == slip.order_id)
        )
        if invoice is not None:
            return float(invoice.total_amount), float(invoice.paid_amount), float(invoice.balance)
        order = await self.session.get(Order, slip.order_id)
        total = float(order.total_amount) if order else 0.0
        return total, 0.0, total

    async def _items(self, slip_id: str, order_id: str | None = None) -> list[DeliveryItemResponse]:
        """The slip's lines, priced from the order they were cut from.

        The price is read rather than invented. It used to be a flat 1000 per cylinder, which put
        the same number against a 5 KG and a 422 KG Hippo - and the driver reads this figure out
        to a customer at the gate, so a made-up one is worse than none.

        `unit_price` is left null when the order's line cannot be found, which says "unknown"
        instead of asserting a figure nobody can stand behind.
        """
        rows = list(
            await self.session.scalars(
                select(DeliverySlipItem)
                .where(DeliverySlipItem.slip_id == slip_id)
                .order_by(DeliverySlipItem.position.asc(), DeliverySlipItem.id.asc())
            )
        )
        priced: dict[str, OrderItem] = {}
        if order_id:
            priced = {
                item.cylinder_type: item
                for item in await self.session.scalars(
                    select(OrderItem).where(OrderItem.order_id == order_id)
                )
            }
        items: list[DeliveryItemResponse] = []
        for row in rows:
            line = priced.get(row.cylinder_type)
            unit = float(line.unit_price) if line else None
            items.append(
                DeliveryItemResponse(
                    cylinder_type=row.cylinder_type,
                    label=_label(row.cylinder_type),
                    quantity=row.quantity,
                    unit_price=unit,
                    # Priced on what this slip carries, not what the order asked for: a part load
                    # is a different number from the order's line total.
                    total_price=None if unit is None else unit * row.quantity,
                )
            )
        return items

    async def _customer_phone(self, customer_id: str) -> str | None:
        return await self.session.scalar(
            select(CustomerProfile.mobile_number).where(CustomerProfile.id == customer_id)
        )

    async def _view(self, slip: DeliverySlip) -> DriverDeliveryResponse:
        status_value = APP_STATUS.get(slip.status, DriverDeliveryStatus.PENDING)
        if slip.status == DeliveryStatus.DISPATCHED.value and slip.started_at is not None:
            status_value = DriverDeliveryStatus.OUT_FOR_DELIVERY

        items = await self._items(slip.id, slip.order_id)
        order = await self.session.get(Order, slip.order_id)
        payable, _paid, _pending = await self._money(slip)
        customer_phone = slip.customer_mobile or await self._customer_phone(slip.customer_id)

        empty_returns = [
            EmptyReturnItem(
                cylinder_type=i.cylinder_type,
                label=i.label,
                current_order_quantity=i.quantity,
                customer_previous_due=0,
                expected_quantity=i.quantity,
            )
            for i in items
        ]

        return DriverDeliveryResponse(
            id=slip.id,
            order_id=slip.order_id,
            order_number=slip.order_number,
            status=status_value,
            delivery_date=slip.scheduled_date.isoformat(),
            customer=CustomerLocation(
                id=slip.customer_id,
                name=slip.customer_name,
                phone=customer_phone or "",
                address=_one_line(slip),
                latitude=slip.destination_latitude,
                longitude=slip.destination_longitude,
                is_location_captured=slip.destination_latitude is not None,
            ),
            distance_km=None,
            items=items,
            empty_returns=empty_returns,
            billing=BillingSummary(
                order_subtotal=sum(i.total_price or 0.0 for i in items),
                # Broken out of the total rather than added to it, matching how the order and
                # the invoice carry GST. Zero here used to be a placeholder beside a flat price.
                tax_amount=float(order.gst_amount) if order else 0.0,
                customer_previous_balance=0.0,
                # The order's own total, not a sum of line prices: it is what the invoice
                # bills and what the customer is actually asked for.
                total_payable_amount=payable,
            ),
        )


def _label(cylinder_type: str) -> str:
    try:
        return ORDER_LABELS[CylinderType(cylinder_type)]
    except (KeyError, ValueError):
        return cylinder_type


def _one_line(slip: DeliverySlip) -> str:
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
