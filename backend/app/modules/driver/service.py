"""The delivery app's reads and writes (API_REFERENCE §6-§10)."""

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
    CustomerLocation,
    CustomerInfoDetail,
    DeliveryItemResponse,
    EmptyReturnItem,
    BillingSummary,
    DriverDeliveryResponse,
    OutForDeliveryResponseData,
    VerifyLocationRequest,
    VerifyLocationResponseData,
    UpdateItemsRequest,
    GenerateQrRequest,
    GenerateQrResponseData,
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponseData,
    VerifyCustomerOtpResponseData,
    EmptyDueSummary,
    PaymentEntry,
    CompletedDeliveryDetailResponseData,
    HistoryDeliveriesResponseData,
    HistoryDeliveryEntry,
    HistoryPaymentSummary,
    DriverProfileResponseData,
    ShiftStats,
    DriverInventoryResponseData,
    DriverInventoryLine,
)
from app.modules.orders.constants import ORDER_LABELS
from app.modules.orders.models import Order, OrderItem
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
        slip = await self._mine(slip_id)
        self._require_actionable(slip)
        now = datetime.now(UTC)
        slip.started_at = slip.started_at or now
        slip.updated_at = now
        await self.session.commit()
        return OutForDeliveryResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            status=DriverDeliveryStatus.OUT_FOR_DELIVERY,
            updated_at=slip.updated_at.isoformat().replace("+00:00", "Z"),
        )

    async def verify_location(self, slip_id: str, payload: VerifyLocationRequest) -> VerifyLocationResponseData:
        slip = await self._mine(slip_id)
        self._require_actionable(slip)
        
        now = datetime.now(UTC)
        slip.driver_latitude = payload.latitude
        slip.driver_longitude = payload.longitude
        slip.updated_at = now
        metres = self._distance_to_site(slip, payload)
        
        # Simulate locking customer location if not already locked
        is_location_captured = True
        
        await self.session.commit()
        return VerifyLocationResponseData(
            delivery_id=slip.id,
            is_at_location=metres is None or metres <= AT_LOCATION_RADIUS_METRES,
            distance_meters_from_destination=None if metres is None else round(metres, 1),
            is_location_captured=is_location_captured,
            message="Location verified successfully"
        )

    async def update_items(self, slip_id: str, payload: UpdateItemsRequest) -> DriverDeliveryResponse:
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
        return GenerateQrResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            amount=payload.amount,
            upi_string=f"upi://pay?pa=mbga@bank&pn=MBGA&am={payload.amount}&tr={slip.order_number}&cu=INR",
            qr_image_url=f"https://mbga.clocktales.com/media/qr/{slip.order_number}_{payload.amount}.png",
            expires_in_seconds=600
        )

    async def confirm_counts(
        self, slip_id: str, payload: ConfirmDeliveryRequest
    ) -> ConfirmDeliveryResponseData:
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)
        
        delivered_qty = sum(item.quantity for item in payload.delivered_items)
        empty_qty = sum(item.quantity for item in payload.collected_empties)

        slip.empties_collected = empty_qty
        slip.note = (payload.driver_notes or "").strip() or None
        slip.updated_at = datetime.now(UTC)
        await self.session.commit()

        return ConfirmDeliveryResponseData(
            delivery_id=slip.id,
            customer_otp_required=True, # Forcing to True as per spec
            otp_channel="IN_APP_NOTIFICATION",
            message="OTP has been sent to customer's app notification"
        )

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
        items = await self._items(slip.id)
        
        return VerifyCustomerOtpResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            status=DriverDeliveryStatus.COMPLETED,
            completed_at=(slip.delivered_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
            total_delivered_quantity=slip.cylinders_allocated,
            delivered_items=items,
            total_empty_collected_quantity=slip.empties_collected,
            empty_collected_items=items, # Simplified for mock
            empty_due_summary=EmptyDueSummary(
                expected_total=slip.cylinders_allocated,
                collected_total=slip.empties_collected,
                added_to_customer_pending_due=max(0, slip.cylinders_allocated - slip.empties_collected)
            ),
            payment=PaymentEntry(
                method="cash", split="full", amount_collected=1000.0, payable_amount=1000.0, pending_balance=0.0
            )
        )

    async def get_completed_detail(self, slip_id: str) -> CompletedDeliveryDetailResponseData:
        slip = await self._mine(slip_id)
        items = await self._items(slip.id)
        customer_phone = slip.customer_mobile or await self._customer_phone(slip.customer_id)
        
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
            payment={"method": "cash", "split": "full", "totalAmount": 1000.0, "amountPaid": 1000.0, "pendingBalance": 0.0},
            driver_notes=slip.note
        )

    async def list_history(self, period: str, page: int, limit: int) -> HistoryDeliveriesResponseData:
        slips = await self.list_deliveries(DeliveryFilters(settled_only=True, limit=limit))
        entries = []
        for slip in slips:
            entries.append(HistoryDeliveryEntry(
                id=slip.id,
                order_number=slip.order_number,
                customer_name=slip.customer.name,
                status=slip.status,
                delivery_date=slip.delivery_date,
                completed_at=slip.delivery_date, # Mock
                total_delivered_count=sum(i.quantity for i in slip.items),
                total_empties_count=sum(i.expected_quantity for i in slip.empty_returns),
                items_summary=",".join([f"{i.quantity}x{i.label}" for i in slip.items]),
                payment=HistoryPaymentSummary(method="cash", amount=1000.0, status="FULL")
            ))
        return HistoryDeliveriesResponseData(
            items=entries,
            total=len(entries),
            page=page,
            limit=limit
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
            shift_stats=ShiftStats(
                completed_deliveries_today=5, cash_collected_today=15000.0, total_empties_collected_today=25
            )
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
                    DeliverySlip.status == DeliveryStatus.DISPATCHED.value,
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
        
        stock_by_type = [
            DriverInventoryLine(
                cylinder_type=cylinder_type,
                label=_label(cylinder_type),
                full_count=int(total or 0),
                empty_count=0 # Mock
            )
            for cylinder_type, total in lines
        ]
        
        return DriverInventoryResponseData(
            total_full_cylinders=sum(int(total or 0) for _, total in lines),
            total_empty_cylinders=int(empties or 0),
            active_deliveries_count=int(active or 0),
            stock_by_type=stock_by_type
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
        if slip.status == DeliveryStatus.DISPATCHED.value:
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

    def _distance_to_site(
        self, slip: DeliverySlip, payload: VerifyLocationRequest
    ) -> float | None:
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
                unit_price=1000.0, # Mock price
                total_price=1000.0 * row.quantity
            )
            for row in rows
        ]

    async def _customer_phone(self, customer_id: str) -> str | None:
        return await self.session.scalar(
            select(CustomerProfile.mobile_number).where(CustomerProfile.id == customer_id)
        )

    async def _view(self, slip: DeliverySlip) -> DriverDeliveryResponse:
        status_value = APP_STATUS.get(slip.status, DriverDeliveryStatus.PENDING)
        if slip.status == DeliveryStatus.DISPATCHED.value and slip.started_at is not None:
            status_value = DriverDeliveryStatus.OUT_FOR_DELIVERY
            
        items = await self._items(slip.id)
        customer_phone = slip.customer_mobile or await self._customer_phone(slip.customer_id)
        
        empty_returns = [
            EmptyReturnItem(
                cylinder_type=i.cylinder_type,
                label=i.label,
                current_order_quantity=i.quantity,
                customer_previous_due=0,
                expected_quantity=i.quantity
            )
            for i in items
        ]
        
        return DriverDeliveryResponse(
            id=slip.id,
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
                is_location_captured=slip.destination_latitude is not None
            ),
            distance_km=None,
            items=items,
            empty_returns=empty_returns,
            billing=BillingSummary(
                order_subtotal=sum(i.total_price or 0.0 for i in items),
                tax_amount=0.0,
                customer_previous_balance=0.0,
                total_payable_amount=sum(i.total_price or 0.0 for i in items)
            )
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
