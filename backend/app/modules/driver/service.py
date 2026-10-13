"""The delivery app's reads and writes (API_REFERENCE §6-§10)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import status as http_status
from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.constants.models import Constant
from app.modules.constants.seeds import CANCELLATION_REASONS
from app.modules.credit.service import CreditLimitService
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.deliveries import validation
from app.modules.deliveries.constants import (
    ALL_STATUSES,
    CANCELLATION_REASON_LABELS,
    IN_TRANSIT_STATUSES,
    LIVE_STATUSES,
    REASONS_REQUIRING_NOTES,
    CancellationReason,
    DeliveryStatus,
)
from app.modules.deliveries.empties import CustomerEmpties
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
    AvailableCylinderTypeItem,
    AvailableCylinderTypesResponseData,
    BillingSummary,
    CancelDeliveryRequest,
    CancelDeliveryResponseData,
    CancellationReasonOption,
    CancellationReasonsResponseData,
    CompletedDeliveryDetailResponseData,
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponseData,
    CustomerInfoDetail,
    CustomerLocation,
    DaySummaryLine,
    DaySummaryResponseData,
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
    PaymentSummaryResponseData,
    ShiftStats,
    UpdateItemsRequest,
    VerifyCustomerOtpResponseData,
    VerifyLocationRequest,
    VerifyLocationResponseData,
)
from app.modules.driver.upi_qr import build_upi_link, png_base64
from app.modules.merchants.models import Merchant
from app.modules.orders import transitions
from app.modules.orders.amendment import AmendedLine, OrderAmender, merge
from app.modules.orders.constants import ORDER_LABELS, OrderStatus
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.constants import (
    OFFERED_PAYMENT_MODES,
    PaymentMode,
    ReconciliationStatus,
)
from app.modules.payments.invoicing import delivered_total
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.schemas import RecordPaymentRequest
from app.modules.payments.service import PaymentService
from app.modules.pricing.constants import (
    ACTIVE_TIER,
    CYLINDER_LABELS,
    CylinderType,
    cylinders_for,
)
from app.modules.pricing.service import resolve_customer_price, tier_prices_for_month
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.date_time.business_calendar import business_day_window, business_today
from app.shared.exceptions.api_error import ApiError
from app.shared.geo.distance import haversine_metres


def _not_found() -> ApiError:
    return ApiError("DELIVERY_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class DeliveryFilters:
    scheduled_on: Any = None
    settled_only: bool = False
    #: Also show open slips from **before** `scheduled_on`. A slip that was never dispatched
    #: does not expire: it keeps its old date, drops off the driver's list the next morning,
    #: and nobody can close it again - the driver cannot see it and the office has no endpoint
    #: for it. The order behind it stays open for ever and the customer is never told.
    include_overdue: bool = False
    limit: int = 50


#: The history tabs the delivery app offers. `week` is the last seven days including today,
#: which is what "This Week" means to somebody looking at their own round - not a calendar week
#: that empties out every Monday morning.
HISTORY_WINDOWS: dict[str, int] = {"today": 0, "week": 6, "this_week": 6}


def _history_window(period: str, today: date) -> date | None:
    """The earliest day a history tab shows, or `None` for all of it.

    An unknown value falls back to everything rather than to nothing: a tab the app adds
    tomorrow should show too much, not an empty screen the driver reads as "no deliveries".
    """
    days = HISTORY_WINDOWS.get((period or "").strip().lower())
    return None if days is None else today - timedelta(days=days)


#: What a settled round can have ended as. A history tab shows both; a "completed" screen asks
#: for one.
#:
#: Keyed on the words the driver's app already reads back off each row - `completed`, `failed`
#: - as well as the stored codes, so the filter is asked for in the same vocabulary the list
#: answers in. A screen showing rows marked "completed" should not have to know that the
#: database calls them DELIVERED.
#:
#: Anything else falls back to both rather than to an empty list, the same way the period window
#: does: a screen reading "no deliveries" is the worst possible answer to a typo.
HISTORY_OUTCOMES: dict[str, tuple[str, ...]] = {
    DriverDeliveryStatus.COMPLETED.value: (DeliveryStatus.DELIVERED.value,),
    DeliveryStatus.DELIVERED.value.lower(): (DeliveryStatus.DELIVERED.value,),
    DriverDeliveryStatus.FAILED.value: (DeliveryStatus.FAILED.value,),
}
_BOTH_OUTCOMES: tuple[str, ...] = (DeliveryStatus.DELIVERED.value, DeliveryStatus.FAILED.value)


def _history_statuses(status: str) -> tuple[str, ...]:
    """Which outcomes the history list shows. Unknown or `ALL` means both."""
    return HISTORY_OUTCOMES.get((status or "").strip().lower(), _BOTH_OUTCOMES)


def _as_instant(moment: datetime | None) -> str | None:
    """A stored timestamp as an instant the app can convert to the reader's own clock.

    MySQL `DATETIME` keeps no offset, so what comes back is naive UTC. Rendering it with
    `.isoformat()` produced `"2026-10-09T11:30:00"`, which a phone reads as **local** time -
    11:30 AM on a receipt for a delivery made at 5 PM IST. Marking it UTC and ending it with
    `Z` is what the delivery board already does, and it leaves the conversion where it belongs:
    on the device that knows what clock the person is looking at.
    """
    if moment is None:
        return None
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")



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
            if filters.include_overdue:
                # Today's round, plus anything older that is still open. The driver is the one
                # who knows what happened on those days, and he can only act on what he is
                # shown.
                statement = statement.where(
                    or_(
                        DeliverySlip.scheduled_date == filters.scheduled_on,
                        and_(
                            DeliverySlip.scheduled_date < filters.scheduled_on,
                            DeliverySlip.status.in_(tuple(LIVE_STATUSES)),
                        ),
                    )
                )
            else:
                statement = statement.where(
                    DeliverySlip.scheduled_date == filters.scheduled_on
                )
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

    async def available_cylinder_types(
        self, slip_id: str
    ) -> AvailableCylinderTypesResponseData:
        """Choices for the delivery app's doorstep ``Update Order`` sheet.

        The order's pricing month is intentional: adding a cylinder at the gate must use the
        same rate card as the order, while still respecting a customer-specific override.
        """
        slip = await self._mine(slip_id)
        self._require_actionable(slip)
        customer = await self.session.get(CustomerProfile, slip.customer_id)
        order = await self.session.get(Order, slip.order_id)
        if customer is None or order is None:
            raise _not_found()
        if not order.pricing_month_id:
            raise ApiError(
                "PRICING_NOT_CONFIGURED",
                http_status.HTTP_409_CONFLICT,
                "This order has no pricing month, so its doorstep prices cannot be resolved.",
            )

        customer_type = (customer.customer_type or order.customer_type or "RETAIL").upper()
        tier = customer.pricing_tier or ACTIVE_TIER.value
        tier_prices = await tier_prices_for_month(self.session, order.pricing_month_id, tier)
        if not tier_prices and tier != ACTIVE_TIER.value:
            tier_prices = await tier_prices_for_month(
                self.session, order.pricing_month_id, ACTIVE_TIER.value
            )

        items: list[AvailableCylinderTypeItem] = []
        for cylinder_type in cylinders_for(customer_type):
            price = await resolve_customer_price(
                self.session,
                customer.id,
                cylinder_type.value,
                tier_prices.get(cylinder_type.value),
            )
            if price is None:
                raise ApiError(
                    "CYLINDER_PRICE_NOT_CONFIGURED",
                    http_status.HTTP_409_CONFLICT,
                    f"Price is not configured for {cylinder_type.value}.",
                )
            items.append(
                AvailableCylinderTypeItem(
                    cylinderType=cylinder_type.value,
                    label=CYLINDER_LABELS[cylinder_type],
                    unitPrice=float(price),
                )
            )

        return AvailableCylinderTypesResponseData(
            deliveryId=slip.id,
            customerType=customer_type,
            cylinderTypes=items,
        )

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
            # The order first. Cancelling an order fails its slip, so a driver whose phone still
            # shows a cancelled round would otherwise be told his slip is settled - the
            # consequence - rather than that the order was cancelled, which is the reason and
            # the thing his app branches on to reload.
            # Locked, so this reads the row as it stands rather than this transaction's
            # snapshot of it: a cancellation committed a moment ago has to be seen, or two
            # requests that raced each other both report success and the later one wins.
            order = await self.session.get(Order, slip.order_id, with_for_update=True)
            if order is not None:
                transitions.check_can_move(order, OrderStatus.OUT_FOR_DELIVERY)
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
            FailDeliveryRequest(reason=payload.stated_reason),
        )
        await self.session.refresh(slip)
        return CancelDeliveryResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            delivery_status=DeliveryStatus.FAILED.value,
            order_status="CANCELLED",
            cancelled_at=slip.updated_at.isoformat().replace("+00:00", "Z"),
        )

    async def cancellation_reasons(self) -> CancellationReasonsResponseData:
        """The dropdown behind "Cancel delivery", decided here rather than in the app.

        The codes are the platform's, so a reason the cancel endpoint would refuse can never be
        offered. The labels are read from `constants`, where an operator may reword them without
        a release - a merchant who calls it "Gate locked" rather than "Shop closed" should not
        need one.
        """
        worded = {
            row.const_key: row.const_value
            for row in await self.session.scalars(
                select(Constant).where(Constant.const_group == CANCELLATION_REASONS)
            )
        }
        return CancellationReasonsResponseData(
            items=[
                CancellationReasonOption(
                    code=reason.value,
                    label=worded.get(reason.value, CANCELLATION_REASON_LABELS[reason]),
                    requiresNotes=reason in REASONS_REQUIRING_NOTES,
                    sortOrder=order + 1,
                )
                for order, reason in enumerate(CancellationReason)
            ]
        )

    async def verify_location(
        self, slip_id: str, payload: VerifyLocationRequest
    ) -> VerifyLocationResponseData:
        """The driver is at the gate: record where that is.

        `isLocationCaptured` was hard-coded to `True`, so the app was told the customer's
        address had coordinates whether or not anybody had ever recorded them - which is
        exactly the screen that was supposed to get them recorded.
        """
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        now = datetime.now(UTC)
        slip.driver_latitude = payload.latitude
        slip.driver_longitude = payload.longitude
        metres = self._distance_to_site(slip, payload)
        is_location_captured = await self._capture_destination(slip, payload, now)

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
        """Change what this delivery is carrying, at the gate (spec: doorstep `Update Order`).

        The customer asks for one more cylinder, or decides against one, while the driver is
        standing there. The order was fixed the moment it was confirmed, so the only answers
        were a second order - a second bill with a second number for one visit - or cancelling
        the whole thing and placing it again.

        **This endpoint existed and did nothing.** It took the new basket, discarded it, wrote
        the reason onto the slip as a note and returned success, so the app could complete the
        flow while the order it was meant to change stayed exactly as it was.

        Lines already on the order keep the price they were placed at; a type new to the order
        is priced from the order's own rate card, which is what the doorstep sheet quoted.

        **Only before the handover completes.** The bill is raised when the customer's code is
        read out, so until then this simply changes what will be billed; afterwards the invoice
        exists and a printed bill is not edited.
        """
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)
        self._require_actionable(slip)

        merchant = await self.session.get(Merchant, slip.merchant_id)
        order = await self.session.get(Order, slip.order_id, with_for_update=True)
        if order is None:  # pragma: no cover - a slip always has its order
            raise _not_found()
        billed = await self.session.scalar(select(Invoice.id).where(Invoice.order_id == order.id))
        if billed is not None:
            raise ApiError(
                "DELIVERY_ALREADY_SETTLED",
                http_status.HTTP_409_CONFLICT,
                f"Order {order.order_number} is already billed and cannot be changed.",
            )

        before = order.items_summary
        wanted = merge(
            [AmendedLine(line.cylinder_type, line.quantity) for line in payload.updated_items]
        )
        amender = OrderAmender(
            self.session, slip.merchant_id, merchant.code if merchant else None
        )
        revised_total = await amender.projected_total(order, wanted)
        await CreditLimitService(self.session).enforce_fail_open(
            order.customer_id,
            revised_total,
            replacing_order_id=order.id,
        )
        # The blocking check may commit its notification before refusing. Re-lock/re-read the
        # order so the actual amendment is still based on current data.
        order = await self.session.get(Order, slip.order_id, with_for_update=True)
        await amender.amend(order, wanted)
        await self._recut(slip, order)

        reason = (payload.reason or "").strip()
        transitions.note(
            self.session,
            order,
            note=f"Order changed at the gate: {before} -> {order.items_summary}"
            + (f" ({reason})" if reason else ""),
            by_name=self.actor.display_name,
            by_user_id=self.actor.user_id,
            by_role="driver",
            source=self.actor.source,
        )
        await self.session.commit()
        await self.session.refresh(slip)
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
        await self._check_qr_amount(slip, Decimal(amount))
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

    async def _check_qr_amount(self, slip: DeliverySlip, amount: Decimal) -> None:
        """Hold the QR to the same ceiling as the payment, and leave a trace that it was shown.

        A QR used to be built for any figure at all - a 1,690 delivery could be asked to pay
        50,000 and the customer's app would show it without a murmur. The payment that follows is
        capped at what the delivery comes to, so an unchecked QR could only ever produce money
        the platform would then refuse to record.

        The ceiling is what this delivery will be billed for, which on a part handover is less
        than the order. When the driver has not yet stated his counts there are none to read, and
        the order's own total is the honest ceiling.

        Recorded because nothing else records it. There is no gateway here - the agency collects
        on a personal VPA - so this row and the driver's photo are the only evidence the office
        has that a UPI collection was asked for at all.
        """
        payable = await self._collectable(slip)
        if amount > payable:
            raise ApiError(
                "QR_AMOUNT_EXCEEDS_PAYABLE",
                http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"This customer owes {payable} in all, so a QR for {amount} cannot be shown.",
                fields=[
                    {
                        "field": "amount",
                        "code": "exceeds_payable",
                        "message": f"The most that can be collected is {payable}.",
                    }
                ],
            )
        slip.qr_amount = int(amount)
        slip.qr_generated_at = datetime.now(UTC)
        await self.session.commit()

    async def confirm_counts(
        self, slip_id: str, payload: ConfirmDeliveryRequest
    ) -> ConfirmDeliveryResponseData:
        """Record what the driver is handing over and what he is collecting for it.

        Nothing is banked here. The counts and the payment are written onto the slip and acted on
        when the customer's code completes the handover - the invoice this payment pays does not
        exist until then, because the bill is raised at handover.

        The payment is **checked** here all the same, against what these counts will come to.
        This is the moment the driver is standing at the gate and can still fix a wrong figure;
        refusing it later, after the customer has the cylinders and the code has been read out,
        would leave him holding money the system will not take.
        """
        slip = await self._mine(slip_id)
        self._require_dispatched(slip)

        empty_qty = sum(item.quantity for item in payload.collected_empties)
        # Checked HERE, on the screen the driver is typing the empties into, and not left to
        # the customer's code. The ceiling used to be reached only at `verify-customer-otp`,
        # which refused the handover at the last step with a message about the wrong field -
        # the driver read it as the customer reading out a wrong code.
        owed = await CustomerEmpties(self.session, slip.merchant_id).outstanding(
            slip.customer_id, ignoring=slip.id
        )
        validation.check_empties(
            empty_qty, slip.cylinders_allocated, previous_due=sum(owed.values())
        )

        await self._record_delivered(slip, payload.delivered_items)
        await self._record_empties(slip, payload.collected_empties)
        await self._record_payment_intent(slip, payload.payment)
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

    async def _record_empties(self, slip: DeliverySlip, collected: list[Any]) -> None:
        """Write the per-size empties beside the per-size handover.

        The slip keeps the total, which is what the stock ledger books; this keeps the split,
        which is what the receipt prints and what the godown counts back in. Summing on arrival
        and discarding the breakdown left the receipt listing the delivered lines in the empties
        column - a total of 2 printed above rows adding to 3.

        A type the driver does not mention is recorded as zero rather than left null: his list
        is a complete statement, the same as `deliveredItems`.

        **Not capped at what was delivered.** A customer returns the empties they have, which
        on a refill round is last month's cylinders and need not match today's handover.
        """
        rows = {
            row.cylinder_type: row
            for row in await self.session.scalars(
                select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
            )
        }
        counts: dict[str, int] = {}
        for item in collected:
            counts[item.cylinder_type] = counts.get(item.cylinder_type, 0) + item.quantity

        # A size the customer is handing back but did not order today - last month's 19 KG
        # returned on a visit that is delivering 5 KG. This was refused outright, which left
        # the shell standing in the customer's yard with no way to book it in. It gets a line
        # of its own with nothing allocated against it: nothing was sold, something came back.
        for cylinder_type, quantity in counts.items():
            if cylinder_type in rows or not quantity:
                continue
            extra = DeliverySlipItem(
                slip_id=slip.id,
                cylinder_type=cylinder_type,
                quantity=0,
                delivered_quantity=0,
                empties_collected=0,
                position=len(rows) + 1,
            )
            self.session.add(extra)
            rows[cylinder_type] = extra

        for cylinder_type, row in rows.items():
            row.empties_collected = counts.get(cylinder_type, 0)

    async def _record_payment_intent(self, slip: DeliverySlip, payment: PaymentEntry | None) -> None:
        """Park the money the driver says he took, having checked it is money that can be taken.

        An amount of zero is a real answer - the customer is paying later - and leaves the slip
        with no payment at all rather than a zero one.

        **Over-collection is refused**, here as in the merchant panel: the platform has no
        customer wallet, so anything above the bill would be money with nowhere to sit and no
        record of the merchant owing it back. The ceiling is what these very counts will be
        billed for, which on a part delivery is less than the order - a driver who hands over two
        of four cylinders may not collect for four.
        """
        if payment is None:
            return
        amount = int(round(payment.amount_collected))
        if amount <= 0:
            slip.payment_mode = None
            slip.payment_amount = None
            slip.payment_reference = None
            return

        try:
            mode = PaymentMode(str(payment.method).upper())
        except ValueError:
            mode = None
        # Checked against what is **offered**, not merely against the enum: that is wider, so
        # that payments taken in a mode since withdrawn keep reading back. A driver may only
        # collect in a mode money is actually taken in today.
        if mode not in OFFERED_PAYMENT_MODES:
            raise ApiError(
                "PAYMENT_MODE_INVALID",
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{payment.method} is not a payment mode this platform accepts.",
            )

        reference = (payment.reference or "").strip() or None
        # **Not demanded for UPI**, although the merchant panel still asks the office for one.
        # The UTR appears on the *customer's* phone, and the driver's screen has nowhere to put
        # it; requiring it would make UPI uncollectable at the gate, which is where UPI is
        # collected. The payment lands `PENDING` and the office settles it against the bank
        # statement, matching on the amount and the time - which is what `qr_amount` and
        # `qr_generated_at` are recorded for.

        payable = await self._collectable(slip)
        if amount > payable:
            raise ApiError(
                "PAYMENT_EXCEEDS_PAYABLE",
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"This customer owes {payable} in all, so {amount} cannot be collected.",
            )

        slip.payment_mode = mode.value
        slip.payment_amount = amount
        slip.payment_reference = reference

    async def _collectable(self, slip: DeliverySlip) -> int:
        """The most the driver may take at this gate: this delivery **plus** what was owed.

        A driver standing in front of the customer can be handed the arrears as well, and the
        screen now asks for them - so capping at today's cylinders would refuse money the
        customer is holding out. The surplus is applied to the older invoices; see
        `_bank_payment`.

        Whole rupees, because a payment is.
        """
        order = await self.session.get(Order, slip.order_id)
        delivery = (
            await delivered_total(self.session, order, await self._delivered_counts(slip))
            if order
            else 0
        )
        return int(delivery + await self._previous_due(slip))

    async def _delivered_counts(self, slip: DeliverySlip) -> dict[str, int]:
        """The per-type handover counts as they now stand on the slip.

        Read back from the rows `_record_delivered` has just written rather than from the request
        again, so the payment is checked against the figure that will actually be billed.
        """
        rows = await self.session.scalars(
            select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
        )
        return {
            row.cylinder_type: (
                row.quantity if row.delivered_quantity is None else row.delivered_quantity
            )
            for row in rows
        }

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
        await self._bank_payment(slip)
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
            completed_at=_as_instant(slip.delivered_at) or _as_instant(datetime.now(UTC)),
            total_delivered_quantity=delivered_total,
            delivered_items=items,
            total_empty_collected_quantity=slip.empties_collected,
            empty_collected_items=await self._empty_items(slip),
            empty_due_summary=EmptyDueSummary(
                expected_total=delivered_total,
                collected_total=slip.empties_collected,
                added_to_customer_pending_due=max(0, delivered_total - slip.empties_collected),
            ),
            payment=await self._collected_view(slip, payable, paid, pending),
        )

    async def _collected_view(
        self, slip: DeliverySlip, payable: float, paid: float, pending: float
    ) -> PaymentEntry:
        """What the driver actually took, and where it went.

        This block used to report the **invoice's** figures: a driver handed 1,819 - today's
        1,390 plus 429 of arrears - and the receipt said 1,390 collected, 1,390 payable, as
        though the rest had been dropped. It had not; it was applied to the older invoices. The
        block simply could not see past this delivery.

        `method` was the literal string "cash" whatever had happened, for want of anything
        recorded to read. It now comes from the payment itself.
        """
        collected = float(slip.payment_amount or 0)
        on_this_delivery = min(collected, paid)
        remaining_elsewhere = await self._previous_due(slip)
        return PaymentEntry(
            method=(slip.payment_mode or "").lower() or "none",
            split="full" if pending + remaining_elsewhere <= 0 else "partial",
            amountCollected=collected,
            # What the customer was asked for: this delivery plus what stood before it.
            payableAmount=payable + remaining_elsewhere + (collected - on_this_delivery),
            # Everything still owed once this collection has landed, not this invoice alone.
            pendingBalance=pending + remaining_elsewhere,
            reference=slip.payment_reference,
            appliedToThisDelivery=on_this_delivery,
            appliedToPreviousDue=round(collected - on_this_delivery, 2),
        )

    async def _previous_due(self, slip: DeliverySlip) -> float:
        """What this customer still owes on **other** deliveries, with GST already inside.

        This delivery's own invoice is left out so the two figures can be added without counting
        it twice: the driver's screen shows "this delivery" and "previously due" side by side,
        and their sum is what the customer is being asked for in total.

        Before the handover there is no invoice for this delivery, so every open invoice is a
        previous one; afterwards there is, and it is excluded by id.
        """
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.balance), 0)).where(
                Invoice.customer_id == slip.customer_id,
                Invoice.merchant_id == slip.merchant_id,
                Invoice.order_id != slip.order_id,
            )
        )
        return float(total or 0)

    async def payment_summary(self, slip_id: str) -> PaymentSummaryResponseData:
        """Everything the payment screen needs to decide what to collect.

        One call rather than three, because the three figures have to agree with each other on
        one screen: what this delivery comes to, what the customer already owed, and what a QR
        may therefore be raised for. Assembling that in the app meant each number came from a
        different request and a different moment.

        `maxQrAmount` is everything the customer owes: this delivery plus the arrears. The
        driver is in front of them and can be handed both, so capping at today's cylinders
        would refuse money the customer is holding out. Whatever is collected above this
        delivery's own bill is applied to the older invoices, oldest first.
        """
        slip = await self._mine(slip_id)
        order = await self.session.get(Order, slip.order_id)
        payable, paid, pending = await self._money(slip)
        previous = await self._previous_due(slip)

        merchant = await self.session.get(Merchant, slip.merchant_id)
        upi_ready = bool(merchant and merchant.upi_id and merchant.upi_payee_name)

        return PaymentSummaryResponseData(
            delivery_id=slip.id,
            order_number=slip.order_number,
            customer_name=slip.customer_name,
            delivery_amount=payable,
            amount_paid=paid,
            pending_amount=pending,
            customer_previous_due=previous,
            total_due=pending + previous,
            max_qr_amount=pending + previous,
            upi_available=upi_ready,
            upi_id=merchant.upi_id if upi_ready else None,
            payee_name=merchant.upi_payee_name if upi_ready else None,
            last_qr_amount=float(slip.qr_amount) if slip.qr_amount is not None else None,
            last_qr_at=(
                slip.qr_generated_at.isoformat().replace("+00:00", "Z")
                if slip.qr_generated_at
                else None
            ),
            modes=[mode.value for mode in sorted(OFFERED_PAYMENT_MODES)],
        )

    async def _bank_payment(self, slip: DeliverySlip) -> None:
        """Turn the money parked on the slip into a payment against the invoice just raised.

        Runs after the handover is confirmed, because that is when the invoice exists. The
        amount was already checked against what this delivery would be billed for, so it fits
        the balance by construction.

        **Silent when there is nothing to bank**, which covers a customer paying later and a slip
        the office confirmed itself. Silent too when the handover raised no invoice, which happens
        only when nothing was handed over - and nothing handed over cannot have been paid for.

        A payment recorded twice would double a customer's credit, so a slip that already has one
        is left alone: `verify_customer_otp` is safe to retry after a timeout.
        """
        if not slip.payment_amount or not slip.payment_mode:
            return
        invoice = await self.session.scalar(
            select(Invoice).where(Invoice.order_id == slip.order_id)
        )
        if invoice is None:
            return
        already = await self.session.scalar(
            select(Payment.id).where(
                Payment.invoice_id == invoice.id,
                Payment.collected_by_user_id == self.driver_user_id,
            )
        )
        if already is not None:
            return

        payments = PaymentService(self.session, self._merchant_actor(slip))
        for target, amount in await self._allocate(slip, invoice):
            await payments.record(
                RecordPaymentRequest(
                    invoiceId=target.id,
                    amount=amount,
                    mode=PaymentMode(slip.payment_mode),
                    reference=slip.payment_reference,
                    note=f"Collected on delivery {slip.order_number}",
                ),
                # The gate, not the office. See `PaymentService.record`.
                reference_required=False,
            )

    async def _allocate(
        self, slip: DeliverySlip, invoice: Invoice
    ) -> list[tuple[Invoice, int]]:
        """Spread what the driver collected across the invoices it pays.

        The driver may be handed the arrears along with today's bill, so the money can be more
        than this delivery comes to. A payment is recorded against one invoice, and
        over-collection against it is refused - rightly, since the platform has no wallet for
        the surplus to sit in. So the amount is split: **this delivery first**, because that is
        what the customer is being handed cylinders for, then the older invoices **oldest
        first**, which is how a debt is cleared everywhere else.

        One `Payment` row per invoice. A single row spanning several would leave each invoice's
        `paidAmount` to be inferred, and the trail would not say which bill the money cleared.

        Anything left over after every open invoice is settled is dropped rather than banked.
        It cannot happen - the ceiling at the gate is the same total - and if it ever did, a
        payment with nowhere to sit is worse than one rupee unaccounted for.
        """
        remaining = int(slip.payment_amount or 0)
        plan: list[tuple[Invoice, int]] = []

        others = await self.session.scalars(
            select(Invoice)
            .where(
                Invoice.customer_id == slip.customer_id,
                Invoice.merchant_id == slip.merchant_id,
                Invoice.id != invoice.id,
                Invoice.balance > 0,
            )
            .order_by(Invoice.issued_at, Invoice.id)
        )
        for target in (invoice, *others):
            if remaining <= 0:
                break
            share = min(remaining, int(target.balance))
            if share <= 0:
                continue
            plan.append((target, share))
            remaining -= share
        return plan

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
            completed_at=_as_instant(slip.delivered_at) or _as_instant(datetime.now(UTC)),
            customer=CustomerInfoDetail(
                name=slip.customer_name, phone=customer_phone or "", address=_one_line(slip)
            ),
            delivered_items=items,
            empty_items=await self._empty_items(slip),
            payment=await self._payment_view(slip, payable, paid, pending),
            driver_notes=slip.note,
        )

    async def _payment_view(
        self, slip: DeliverySlip, payable: float, paid: float, pending: float
    ) -> dict[str, object]:
        """How this delivery was paid for, read from the payments banked against its invoice.

        `method` used to be the string "cash" whatever had happened, because nothing was recorded
        and there was nothing to read. It is now the mode of the payments themselves - `null`
        when none has landed, and "mixed" for the customer who pays part in cash and the rest by
        UPI, which an invoice is free to have.
        """
        invoice = await self.session.scalar(
            select(Invoice).where(Invoice.order_id == slip.order_id)
        )
        modes: list[str] = []
        if invoice is not None:
            rows = list(
                await self.session.scalars(
                    select(Payment).where(
                        Payment.invoice_id == invoice.id,
                        Payment.reconciliation_status != ReconciliationStatus.INVALID.value,
                    )
                )
            )
            modes = sorted({row.mode for row in rows})
        method = modes[0].lower() if len(modes) == 1 else ("mixed" if modes else None)
        return {
            "method": method,
            "split": "full" if pending <= 0 else ("partial" if paid > 0 else "unpaid"),
            "totalAmount": payable,
            "amountPaid": paid,
            "pendingBalance": pending,
        }

    async def list_history(
        self, period: str, page: int, limit: int, status: str = ALL_STATUSES
    ) -> HistoryDeliveriesResponseData:
        """The driver's settled rounds, newest first, for the window the tab asks for.

        **`period` used to be read and ignored**, so Today, This Week and All returned the same
        unfiltered list; `page` was ignored too, so every page was the first one, and `total`
        reported the length of that page rather than how many there are. `completedAt` was the
        delivery's **date** rather than the moment it was settled.

        Windows are IST calendar days, because that is the day the driver worked - a round
        confirmed at 11pm belongs to that evening, not to the next UTC day.

        `status` narrows settled work to one outcome. The default is both, which is what a
        history tab wants, but a screen showing only what was completed had no way to ask for
        it - so it read the first page and counted the delivered rows on it, which is a
        different number from how many there are and was reported as the total being wrong.
        """
        today = business_today()
        window = _history_window(period, today)

        statement = self._scope(select(DeliverySlip)).where(
            DeliverySlip.status.in_(_history_statuses(status))
        )
        if window is not None:
            statement = statement.where(DeliverySlip.scheduled_date >= window)

        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = list(
            await self.session.scalars(
                statement.order_by(
                    DeliverySlip.scheduled_date.desc(), DeliverySlip.slip_number.desc()
                )
                .offset((max(page, 1) - 1) * limit)
                .limit(limit)
            )
        )

        paid_by_order, pending_by_order = await self._settled_money([row.id for row in rows])
        entries = []
        for slip in rows:
            items = await self._items(slip.id, slip.order_id)
            collected = await self._empty_items(slip)
            entries.append(
                HistoryDeliveryEntry(
                    id=slip.id,
                    order_number=slip.order_number,
                    customer_name=slip.customer_name,
                    status=APP_STATUS.get(slip.status, DriverDeliveryStatus.PENDING).value,
                    delivery_date=slip.scheduled_date.isoformat(),
                    # The moment it was settled, as an instant. MySQL keeps no offset, so a
                    # naive read is marked UTC rather than left to be read as local time.
                    completed_at=_as_instant(slip.delivered_at),
                    total_delivered_count=sum(i.quantity for i in items),
                    # What actually came back, not what was expected to: the expected figure
                    # was what this line reported, so a round that collected nothing still
                    # showed the day's quota.
                    total_empties_count=sum(i.quantity for i in collected),
                    items_summary=slip.items_summary or "",
                    payment=HistoryPaymentSummary(
                        method=(slip.payment_mode or "").lower() or "none",
                        amount=paid_by_order.get(slip.id, 0.0),
                        status="FULL" if pending_by_order.get(slip.id, 0.0) <= 0 else "PARTIAL",
                    ),
                )
            )
        return HistoryDeliveriesResponseData(
            items=entries, total=int(total or 0), page=page, limit=limit
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

    async def day_summary(self) -> DaySummaryResponseData:
        """What this driver has handed over and taken back today, size by size.

        The godown asks two questions at the end of a round - how many cylinders went out and
        how many shells came back - and the driver had no screen that answered either per size.
        `GET /driver/inventory` answers a different question: what is on the van right now.

        Read off the slips themselves rather than kept as a running total, so it cannot drift
        from the deliveries it describes. Completed work only: a slip still on the van has not
        happened yet.

        **Today is the day the handover happened**, matching the counters on the profile. A
        round planned for yesterday and closed this morning is this morning's work, and the two
        screens would be describing different days if one read `scheduledDate` and the other
        did not.
        """
        today = business_today()
        started, ended = business_day_window(today)
        rows = (
            await self.session.execute(
                select(
                    DeliverySlipItem.cylinder_type,
                    func.coalesce(
                        func.sum(
                            func.coalesce(
                                DeliverySlipItem.delivered_quantity, DeliverySlipItem.quantity
                            )
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(DeliverySlipItem.empties_collected), 0),
                )
                .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
                .where(
                    DeliverySlip.driver_user_id == self.driver_user_id,
                    DeliverySlip.delivered_at >= started,
                    DeliverySlip.delivered_at < ended,
                    DeliverySlip.status == DeliveryStatus.DELIVERED.value,
                )
                .group_by(DeliverySlipItem.cylinder_type)
                .order_by(DeliverySlipItem.cylinder_type)
            )
        ).all()
        completed = await self.session.scalar(
            select(func.count())
            .select_from(DeliverySlip)
            .where(
                DeliverySlip.driver_user_id == self.driver_user_id,
                DeliverySlip.delivered_at >= started,
                DeliverySlip.delivered_at < ended,
                DeliverySlip.status == DeliveryStatus.DELIVERED.value,
            )
        )

        by_type = [
            DaySummaryLine(
                cylinder_type=cylinder_type,
                label=_label(cylinder_type),
                delivered=int(delivered or 0),
                empties_collected=int(returned or 0),
            )
            # A size that neither went out nor came back is left out rather than shown as two
            # zeroes: the screen is a tally of the day's work, not a price list.
            for cylinder_type, delivered, returned in rows
            if delivered or returned
        ]
        return DaySummaryResponseData(
            date=today.isoformat(),
            deliveries_completed=int(completed or 0),
            total_delivered=sum(line.delivered for line in by_type),
            total_empties_collected=sum(line.empties_collected for line in by_type),
            by_type=by_type,
        )

    async def inventory(self) -> DriverInventoryResponseData:
        lines = (
            await self.session.execute(
                select(
                    DeliverySlipItem.cylinder_type,
                    func.sum(DeliverySlipItem.quantity),
                    # Per-size empties were hard-coded to zero here, so a van carrying shells
                    # reported none of them against any size while the total beside it was right.
                    func.coalesce(func.sum(DeliverySlipItem.empties_collected), 0),
                )
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
                empty_count=int(returned or 0),
            )
            for cylinder_type, total, returned in lines
        ]

        return DriverInventoryResponseData(
            total_full_cylinders=sum(int(total or 0) for _, total, _r in lines),
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

        **Today means the day the work happened**, not the day the round was scheduled for.
        Counting by `scheduled_date` put a leftover from yesterday, closed this morning, onto
        yesterday's figure - a day the driver can no longer see - so his screen read one short
        for work he had just done.
        """
        today = business_today()
        started, ended = business_day_window(today)
        slips = list(
            await self.session.scalars(
                self._scope(select(DeliverySlip)).where(
                    DeliverySlip.delivered_at >= started,
                    DeliverySlip.delivered_at < ended,
                    DeliverySlip.status == DeliveryStatus.DELIVERED.value,
                )
            )
        )
        total_completed = await self.session.scalar(
            self._scope(select(func.count()).select_from(DeliverySlip)).where(
                DeliverySlip.status == DeliveryStatus.DELIVERED.value,
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
            total_completed_deliveries=int(total_completed or 0),
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

    async def _empty_items(self, slip: DeliverySlip) -> list[DeliveryItemResponse]:
        """Which sizes of empty cylinder came back, and how many of each.

        Read from the slip's own lines. Both callers used to be handed the **delivered** items
        here, because nothing per type was recorded - which is why a receipt could print
        "Total: 2" above rows adding to 3.

        No price: an empty is returned, not sold, and putting the cylinder's price against it
        would read as a charge. A line nothing came back on is left out rather than shown as a
        zero, and a slip with no per-type figures at all - an older one, or one the office
        confirmed - returns nothing rather than guessing a split.
        """
        rows = await self.session.scalars(
            select(DeliverySlipItem)
            .where(DeliverySlipItem.slip_id == slip.id)
            .order_by(DeliverySlipItem.position)
        )
        return [
            DeliveryItemResponse(
                cylinder_type=row.cylinder_type,
                label=_label(row.cylinder_type),
                quantity=row.empties_collected,
                unit_price=None,
                total_price=None,
            )
            for row in rows
            if row.empties_collected
        ]

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

    async def _empty_returns(
        self, slip: DeliverySlip, items: list[DeliveryItemResponse]
    ) -> list[EmptyReturnItem]:
        """Every size of shell this customer could hand back, not just today's.

        Built from today's lines **plus** what they are still holding from earlier visits. The
        list used to be today's lines alone with `customerPreviousDue` hard-coded to zero, so a
        customer ordering 5 KG was never asked for the 19 KG they took last month - the driver
        was at the gate and the screen did not mention them.

        Today's sizes come first and keep the order they are delivered in; sizes that are only
        owed from before follow. A line the customer owes nothing on still appears when it is
        part of today's order, because the driver must be able to record the shells that come
        back against the cylinders he is handing over right now.
        """
        previous = await CustomerEmpties(self.session, slip.merchant_id).outstanding(
            slip.customer_id, ignoring=slip.id
        )
        returns = [
            EmptyReturnItem(
                cylinder_type=i.cylinder_type,
                label=i.label,
                current_order_quantity=i.quantity,
                customer_previous_due=previous.get(i.cylinder_type, 0),
                expected_quantity=i.quantity + previous.get(i.cylinder_type, 0),
            )
            for i in items
        ]
        today = {i.cylinder_type for i in items}
        returns.extend(
            EmptyReturnItem(
                cylinder_type=kind,
                label=_label(kind),
                current_order_quantity=0,
                customer_previous_due=due,
                expected_quantity=due,
            )
            for kind, due in sorted(previous.items())
            if kind not in today
        )
        return returns

    async def _capture_destination(
        self, slip: DeliverySlip, payload: VerifyLocationRequest, now: datetime
    ) -> bool:
        """Pin the customer's address the first time a driver stands on it.

        Most orders go to an address nobody ever typed coordinates for, so the slip has none
        and the app cannot draw a route. The driver reporting "I am here" is the one moment the
        platform learns where "here" is, and it costs nothing to keep.

        **Only when it is not already known.** A recorded location is the office's or the
        customer's, and a driver parked at the end of the lane must not quietly move it. The
        fix is saved onto the customer's delivery site as well, so the next order knows it too.

        Returns whether the destination has coordinates once this is done.
        """
        if slip.destination_latitude is not None and slip.destination_longitude is not None:
            return True
        if payload.latitude is None or payload.longitude is None:
            return False

        slip.destination_latitude = payload.latitude
        slip.destination_longitude = payload.longitude
        slip.updated_at = now

        order = await self.session.get(Order, slip.order_id)
        site_id = order.delivery_site_id if order else None
        if site_id:
            site = await self.session.get(CustomerDeliverySite, site_id)
            if site is not None and site.latitude is None and site.longitude is None:
                site.latitude = payload.latitude
                site.longitude = payload.longitude
        return True

    async def _recut(self, slip: DeliverySlip, order: Order) -> None:
        """Rebuild the slip's lines from the order's, keeping what the driver already recorded.

        A line he has already counted out keeps its `deliveredQuantity` and its empties: the
        amendment changes what the van is answerable for, not what he has already said crossed
        the gate. A line whose count now exceeds what is allocated is left as it is and refused
        at `/confirm`, which is where delivering more than the slip carries is already caught.
        """
        rows = {
            row.cylinder_type: row
            for row in await self.session.scalars(
                select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
            )
        }
        items = list(
            await self.session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.position)
            )
        )
        wanted = {item.cylinder_type for item in items}
        for position, item in enumerate(items):
            row = rows.get(item.cylinder_type)
            if row is None:
                self.session.add(
                    DeliverySlipItem(
                        slip_id=slip.id,
                        cylinder_type=item.cylinder_type,
                        quantity=item.quantity,
                        position=position,
                    )
                )
                continue
            row.quantity = item.quantity
            row.position = position
        for cylinder_type, row in rows.items():
            # Dropped from the order. A shell of this size may still have come back on this
            # visit, so the line stays at zero allocated rather than being deleted.
            if cylinder_type not in wanted:
                row.quantity = 0

        slip.cylinders_allocated = order.total_cylinders
        slip.items_summary = order.items_summary
        slip.updated_at = datetime.now(UTC)
        await self.session.flush()

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

        empty_returns = await self._empty_returns(slip, items)

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
            billing=_billing(
                payable,
                # Broken **out of** the total rather than added to it, matching how the order
                # and the invoice carry GST. The subtotal used to be the sum of the line
                # totals - the GST-inclusive figure - so it equalled the grand total and the
                # tax line read as though it were being added on top.
                tax=float(order.gst_amount) if order else 0.0,
                # What the customer owed before this delivery. Zero used to be hard-coded,
                # which told a driver at the gate that a customer three deliveries behind was
                # square.
                previous=await self._previous_due(slip),
            ),
        )


def _billing(grand_total: float, *, tax: float, previous: float) -> BillingSummary:
    """The money panel, with both of its sums made to hold.

    `grand_total` is this delivery's own bill - the invoice's once there is one, the order's
    until then. The subtotal is derived from it by taking the GST back out, so the three
    figures reconcile rather than being read from three places that can disagree.

    `totalPayableAmount` carries the old balance. The driver is at the gate asking for money,
    and the figure he reads out is everything the customer owes once these cylinders are
    handed over - not this delivery in isolation, which was what made a customer 96,000 behind
    look square.
    """
    return BillingSummary(
        order_subtotal=round(grand_total - tax, 2),
        tax_amount=tax,
        grand_total=grand_total,
        customer_previous_balance=previous,
        total_payable_amount=round(grand_total + previous, 2),
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
