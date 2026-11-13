import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.finance.settings import audit
from app.modules.inventory.ledger import StockLedger
from app.modules.logistics.models import Trip, TripLoadLine, TripStop
from app.modules.logistics.policy import policy
from app.modules.orders.models import Order
from app.modules.vehicles.models import Vehicle
from app.shared.exceptions.api_error import ApiError

ACTIVE = ("READY", "IN_PROGRESS", "RETURNED", "DISCREPANCY")
SETTLED = ("DELIVERED", "FAILED")


def decode(value, fallback=None):
    return json.loads(value) if value else fallback


def stamp(value):
    return value.replace(tzinfo=UTC).isoformat() if value else None


async def trip_facts_many(session, trip_ids, current=False):
    if not trip_ids:
        return {}
    pair_query = (
        select(TripStop, DeliverySlip)
        .join(DeliverySlip, TripStop.delivery_id == DeliverySlip.id)
        .where(TripStop.trip_id.in_(trip_ids))
        .order_by(TripStop.trip_id, TripStop.sequence)
    )
    if current:
        pair_query = pair_query.with_for_update().execution_options(populate_existing=True)
    pairs = (await session.execute(pair_query)).all()
    ids = [s.id for _, s in pairs]
    lines = (
        (
            await session.scalars(select(DeliverySlipItem).where(DeliverySlipItem.slip_id.in_(ids)))
        ).all()
        if ids
        else []
    )
    targets = {s.id: (stop.trip_id, s.status) for stop, s in pairs}
    facts = {tid: {} for tid in trip_ids}

    def line(tid, code):
        return facts[tid].setdefault(
            code,
            {
                "planned": 0,
                "delivered": 0,
                "collectedEmpty": 0,
                "loadedFilled": 0,
                "openingEmpty": 0,
                "pending": 0,
                "unfulfilled": 0,
            },
        )

    for item in lines:
        tid, status = targets[item.slip_id]
        row = line(tid, item.cylinder_type)
        row["planned"] += item.quantity
        if status == "DELIVERED":
            row["delivered"] += (
                item.delivered_quantity if item.delivered_quantity is not None else item.quantity
            )
            row["collectedEmpty"] += item.empties_collected or 0
            row["unfulfilled"] += max(
                0,
                item.quantity
                - (
                    item.delivered_quantity
                    if item.delivered_quantity is not None
                    else item.quantity
                ),
            )
        elif status == "FAILED":
            row["unfulfilled"] += item.quantity
        else:
            row["pending"] += item.quantity
    for item in (
        await session.scalars(select(TripLoadLine).where(TripLoadLine.trip_id.in_(trip_ids)))
    ).all():
        row = line(item.trip_id, item.cylinder_type)
        row["loadedFilled"] = item.loaded_filled
        row["openingEmpty"] = item.opening_empty
        row["custodyFilled"] = item.remaining_filled
        row["custodyEmpty"] = item.current_empty
    for values in facts.values():
        for row in values.values():
            row["expectedFilled"] = max(0, row["loadedFilled"] - row["delivered"])
            row["expectedEmpty"] = row["openingEmpty"] + row["collectedEmpty"]
    grouped = {tid: [] for tid in trip_ids}
    for pair in pairs:
        grouped[pair[0].trip_id].append(pair)
    return {tid: (grouped[tid], facts[tid]) for tid in trip_ids}


async def trip_facts(session, trip_id, current=False):
    return (await trip_facts_many(session, [trip_id], current))[trip_id]


async def custody(session, merchant_id, exclude_trip_id=None):
    query = select(TripLoadLine).where(
        TripLoadLine.merchant_id == merchant_id,
        TripLoadLine.active.is_(True),
    )
    if exclude_trip_id:
        query = query.where(TripLoadLine.trip_id != exclude_trip_id)
    rows = (
        await session.scalars(
            query.order_by(TripLoadLine.trip_id, TripLoadLine.cylinder_type)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    filled = defaultdict(int)
    empty = defaultdict(int)
    for row in rows:
        filled[row.cylinder_type] += row.remaining_filled
        empty[row.cylinder_type] += row.current_empty
    return dict(filled), dict(empty)


async def record_handover(session, delivery_id, delivered, collected):
    trip_id = await session.scalar(
        select(TripStop.trip_id).where(TripStop.delivery_id == delivery_id)
    )
    if not trip_id:
        return
    codes = set(delivered) | set(collected)
    rows = (
        await session.scalars(
            select(TripLoadLine)
            .where(TripLoadLine.trip_id == trip_id)
            .order_by(TripLoadLine.cylinder_type)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    by_code = {row.cylinder_type: row for row in rows}
    for code in codes:
        row = by_code.get(code)
        if row is None:
            # Older customer empties can have a size not loaded on this trip.
            if delivered.get(code, 0):
                raise ApiError("TRIP_LOAD_SHORT", 409, "Delivery exceeds its loaded stock.")
            trip = await session.get(Trip, trip_id)
            row = TripLoadLine(
                trip_id=trip_id,
                merchant_id=trip.merchant_id,
                cylinder_type=code,
                loaded_filled=0,
                opening_empty=0,
                remaining_filled=0,
                current_empty=0,
            )
            session.add(row)
        if row.remaining_filled < delivered.get(code, 0):
            raise ApiError("TRIP_LOAD_SHORT", 409, "Delivery exceeds remaining vehicle custody.")
        row.remaining_filled -= delivered.get(code, 0)
        row.current_empty += collected.get(code, 0)
    await session.flush()


async def assert_slip_editable(session, delivery_id):
    row = await session.scalar(
        select(Trip.status)
        .join(TripStop, Trip.id == TripStop.trip_id)
        .where(TripStop.delivery_id == delivery_id)
    )
    if row and row not in ("DRAFT", "CANCELLED"):
        raise ApiError(
            "TRIP_LOAD_LOCKED",
            409,
            "This delivery belongs to a loaded trip. Reset the unstarted trip to draft before changing its allocation.",
        )


async def assert_dispatchable(session, delivery_id):
    row = await session.scalar(
        select(Trip)
        .join(TripStop, Trip.id == TripStop.trip_id)
        .where(TripStop.delivery_id == delivery_id)
    )
    if row and row.status != "CANCELLED" and session.info.get("starting_trip") != row.id:
        raise ApiError(
            "USE_TRIP_START",
            409,
            "Start the complete trip from Trips so loading and custody stay consistent.",
        )

    if row is None:
        other = await session.scalar(
            select(Trip.id)
            .join(
                DeliverySlip,
                (DeliverySlip.merchant_id == Trip.merchant_id)
                & (DeliverySlip.vehicle_number == Trip.vehicle_number),
            )
            .where(DeliverySlip.id == delivery_id, Trip.status.in_(ACTIVE))
            .limit(1)
        )
        if other:
            raise ApiError(
                "VEHICLE_TRIP_OPEN",
                409,
                "Reconcile the vehicle's active trip before starting another dispatch.",
            )


class TripService:
    def __init__(self, session, actor, settings, driver=False):
        self.session = session
        self.actor = actor
        self.settings = settings
        self.driver = driver
        self.merchant_id = actor.require_merchant_id()

    async def owned(self, trip_id, lock=False):
        query = select(Trip).where(Trip.id == trip_id, Trip.merchant_id == self.merchant_id)
        if self.driver:
            query = query.where(Trip.driver_user_id == self.actor.user_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(query)
        if row is None:
            raise ApiError("TRIP_NOT_FOUND", 404, "Trip not found.")
        return row

    async def views(self, rows):
        data = await trip_facts_many(self.session, [r.id for r in rows])
        order_ids = [s.order_id for pairs, _ in data.values() for _, s in pairs]
        orders = (
            {
                o.id: o
                for o in (
                    await self.session.scalars(select(Order).where(Order.id.in_(order_ids)))
                ).all()
            }
            if order_ids
            else {}
        )
        config = await policy(self.session, self.merchant_id)
        return [await self.view(r, data[r.id], orders, config) for r in rows]

    async def view(self, row, data=None, orders=None, config=None):
        pairs, facts = data if data is not None else await trip_facts(self.session, row.id)
        orders = (
            orders
            if orders is not None
            else {
                o.id: o
                for o in (
                    await self.session.scalars(
                        select(Order).where(Order.id.in_([s.order_id for _, s in pairs]))
                    )
                ).all()
            }
            if pairs
            else {}
        )
        config = config or await policy(self.session, self.merchant_id)
        code_map = {p.code: p.model_dump() for p in config.priorities}
        verification = decode(row.verification, {})
        return {
            "id": row.id,
            "number": row.number,
            "vehicleNumber": row.vehicle_number,
            "driverUserId": row.driver_user_id,
            "driverName": row.driver_name,
            "startOdometer": row.start_odometer,
            "endOdometer": row.end_odometer,
            "distanceKm": row.end_odometer - row.start_odometer
            if row.end_odometer is not None and row.start_odometer is not None
            else None,
            "date": str(row.scheduled_date),
            "status": row.status,
            "version": row.version,
            "origin": decode(row.origin),
            "destination": decode(row.destination),
            "route": decode(row.route_preview),
            "notes": row.notes,
            "createdAt": stamp(row.created_at),
            "dispatchedAt": stamp(row.dispatched_at),
            "returnedAt": stamp(row.returned_at),
            "verifiedAt": stamp(row.verified_at),
            "verifiedBy": row.verified_by,
            "verificationBlockedReason": "Only another authorized office user can verify this vehicle return."
            if self.driver
            or self.actor.user_id == row.driver_user_id
            or (
                config.requireSeparateReturnVerifier
                and row.return_submitted_by == self.actor.user_id
            )
            else None,
            "returnSubmission": decode(row.return_submission),
            "verification": verification or None,
            "lines": [{"cylinderType": code, **values} for code, values in sorted(facts.items())],
            "stops": [
                {
                    "deliveryId": s.id,
                    "orderId": s.order_id,
                    "orderNumber": s.order_number,
                    "customerName": s.customer_name,
                    "address": ", ".join(
                        v for v in [s.address_line1, s.address_city, s.address_pincode] if v
                    ),
                    "latitude": stop.latitude
                    if stop.latitude is not None
                    else s.destination_latitude,
                    "longitude": stop.longitude
                    if stop.longitude is not None
                    else s.destination_longitude,
                    "sequence": stop.sequence,
                    "pinned": stop.pinned,
                    "status": s.status,
                    "priorityCode": orders[s.order_id].priority_code,
                    "priority": code_map.get(orders[s.order_id].priority_code),
                    "itemsSummary": s.items_summary,
                }
                for stop, s in pairs
            ],
        }

    async def create(self, payload):
        config = await policy(self.session, self.merchant_id)
        ids = payload.deliveryIds
        if len(ids) != len(set(ids)) or len(ids) > config.maxStops:
            raise ApiError(
                "TRIP_STOPS_INVALID", 422, "Select unique stops within the configured trip size."
            )
        raw = payload.model_dump(mode="json")
        raw["deliveryIds"] = ids
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        old = await self.session.scalar(
            select(Trip)
            .where(
                Trip.merchant_id == self.merchant_id, Trip.idempotency_key == payload.idempotencyKey
            )
            .with_for_update()
        )
        if old:
            if old.request_fingerprint != fingerprint:
                raise ApiError("IDEMPOTENCY_CONFLICT", 409)
            return old
        order_ids = (
            await self.session.scalars(
                select(DeliverySlip.order_id).where(
                    DeliverySlip.id.in_(ids), DeliverySlip.merchant_id == self.merchant_id
                )
            )
        ).all()
        order_rows = (
            await self.session.scalars(
                select(Order)
                .where(Order.id.in_(order_ids))
                .order_by(Order.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        if any(o.status != "CONFIRMED" or o.invoice_id for o in order_rows):
            raise ApiError(
                "TRIP_ASSIGNMENT_INVALID",
                409,
                "Only confirmed, uninvoiced orders can be planned into a trip.",
            )
        slips = (
            await self.session.scalars(
                select(DeliverySlip)
                .where(DeliverySlip.id.in_(ids), DeliverySlip.merchant_id == self.merchant_id)
                .order_by(DeliverySlip.id)
                .with_for_update()
            )
        ).all()
        if len(slips) != len(ids):
            raise ApiError("DELIVERY_NOT_FOUND", 404)
        first = slips[0]
        from app.shared.date_time.business_calendar import business_today

        if first.scheduled_date < business_today():
            raise ApiError(
                "TRIP_DATE_INVALID",
                409,
                "Reschedule overdue deliveries before planning a new trip.",
            )
        if not first.driver_user_id or any(
            s.status != "SCHEDULED"
            or (s.vehicle_number, s.driver_user_id, s.scheduled_date)
            != (first.vehicle_number, first.driver_user_id, first.scheduled_date)
            for s in slips
        ):
            raise ApiError(
                "TRIP_ASSIGNMENT_INVALID",
                422,
                "Select scheduled deliveries assigned to one vehicle, driver and delivery date.",
            )
        if await self.session.scalar(
            select(TripStop.delivery_id).where(TripStop.delivery_id.in_(ids)).limit(1)
        ):
            raise ApiError(
                "DELIVERY_ALREADY_IN_TRIP", 409, "A selected delivery already belongs to a trip."
            )
        origin = payload.origin or config.defaultOrigin
        destination = payload.destination or config.defaultDestination or origin
        if origin is None or destination is None:
            raise ApiError(
                "TRIP_DEPOT_REQUIRED",
                422,
                "Set dispatch/return coordinates in App Settings or provide them for this trip.",
            )
        now = datetime.now(UTC)
        trip_id = str(uuid4())
        row = Trip(
            id=trip_id,
            number="TRIP-" + trip_id.replace("-", "")[:12].upper(),
            merchant_id=self.merchant_id,
            vehicle_number=first.vehicle_number,
            driver_user_id=first.driver_user_id,
            driver_name=first.driver_name,
            scheduled_date=first.scheduled_date,
            status="DRAFT",
            version=1,
            idempotency_key=payload.idempotencyKey,
            request_fingerprint=fingerprint,
            origin=origin.model_dump_json(),
            destination=destination.model_dump_json(),
            notes=payload.notes,
            created_by=self.actor.user_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        by_id = {s.id: s for s in slips}
        for index, sid in enumerate(ids):
            self.session.add(
                TripStop(
                    trip_id=row.id,
                    delivery_id=sid,
                    sequence=index + 1,
                    pinned=False,
                    latitude=by_id[sid].destination_latitude,
                    longitude=by_id[sid].destination_longitude,
                )
            )
        audit(self.session, self.actor.user_id, row.id, "Trip draft created")
        await self.session.flush()
        return row

    def check_version(self, row, version):
        if row.version != version:
            raise ApiError("TRIP_CHANGED", 409, "Trip changed. Refresh and review before saving.")

    def changed(self, row, reason):
        row.version += 1
        row.updated_at = datetime.now(UTC)
        audit(self.session, self.actor.user_id, row.id, reason)

    async def sequence(self, row, payload):
        self.check_version(row, payload.expectedVersion)
        if row.status not in ("DRAFT", "READY", "IN_PROGRESS"):
            raise ApiError("TRIP_SEQUENCE_CLOSED", 409)
        pairs, _ = await trip_facts(self.session, row.id, current=True)
        stops = {s.delivery_id: s for s, _ in pairs}
        if (
            len(payload.deliveryIds) != len(set(payload.deliveryIds))
            or set(payload.deliveryIds) != set(stops)
            or not set(payload.pinnedDeliveryIds).issubset(stops)
        ):
            raise ApiError(
                "TRIP_SEQUENCE_INVALID",
                422,
                "Submit every trip delivery exactly once and valid pinned IDs.",
            )
        if row.status == "IN_PROGRESS":
            for stop, slip in pairs:
                if (
                    slip.status in SETTLED or slip.status == "ON_LOCATION"
                ) and payload.deliveryIds.index(slip.id) != stop.sequence - 1:
                    raise ApiError(
                        "TRIP_STOP_FIXED", 409, "Completed or arrived stops cannot move."
                    )
        if len(payload.coordinates) != len({c.deliveryId for c in payload.coordinates}) or not {
            c.deliveryId for c in payload.coordinates
        }.issubset(stops):
            raise ApiError("TRIP_COORDINATES_INVALID", 422)
        for coordinate in payload.coordinates:
            slip = next(s for stop, s in pairs if stop.delivery_id == coordinate.deliveryId)
            if row.status == "IN_PROGRESS" and (
                slip.status in SETTLED or slip.status == "ON_LOCATION"
            ):
                raise ApiError(
                    "TRIP_STOP_FIXED", 409, "Completed/arrived stop coordinates cannot change."
                )
            stops[coordinate.deliveryId].latitude = coordinate.latitude
            stops[coordinate.deliveryId].longitude = coordinate.longitude
        # A temporary non-overlapping range avoids unique-index collisions while swapping rows.
        for i, stop in enumerate(stops.values()):
            stop.sequence = 1000 + i
        await self.session.flush()
        for i, sid in enumerate(payload.deliveryIds):
            stops[sid].sequence = i + 1
            stops[sid].pinned = sid in payload.pinnedDeliveryIds
        preview = decode(row.route_preview, {})
        row.route_preview = (
            json.dumps({**preview, "approved": True})
            if not payload.coordinates
            and preview.get("deliveryIds") == payload.deliveryIds
            and preview.get("basedOnVersion") == payload.expectedVersion
            else None
        )
        self.changed(row, "Trip sequence updated: " + payload.reason)
        await self.session.flush()

    async def action(self, row, payload):
        self.check_version(row, payload.expectedVersion)
        config = await policy(self.session, self.merchant_id)
        if self.driver and payload.action not in ("START", "RETURN"):
            raise ApiError("PERMISSION_DENIED", 403)
        order_ids = (
            await self.session.scalars(
                select(DeliverySlip.order_id)
                .join(TripStop, TripStop.delivery_id == DeliverySlip.id)
                .where(TripStop.trip_id == row.id)
            )
        ).all()
        await self.session.scalars(
            select(Order).where(Order.id.in_(order_ids)).order_by(Order.id).with_for_update()
        )
        pairs, facts = await trip_facts(self.session, row.id, current=True)
        now = datetime.now(UTC)
        if payload.action == "READY":
            if row.status != "DRAFT" or not payload.loads:
                raise ApiError(
                    "TRIP_STATE_INVALID",
                    409,
                    "Only a draft with actual load counts can be marked ready.",
                )
            if any(
                s.status != "SCHEDULED"
                or s.vehicle_number != row.vehicle_number
                or s.driver_user_id != row.driver_user_id
                or s.scheduled_date != row.scheduled_date
                for _, s in pairs
            ):
                raise ApiError(
                    "TRIP_ASSIGNMENT_CHANGED",
                    409,
                    "Delivery assignment changed; cancel this draft and re-plan.",
                )
            # Vehicle row serializes loading and prevents unresolved vehicle custody being reused.
            vehicle = await self.session.scalar(
                select(Vehicle)
                .where(
                    Vehicle.merchant_id == self.merchant_id,
                    Vehicle.number == row.vehicle_number,
                    Vehicle.is_active.is_(True),
                )
                .with_for_update()
            )
            if vehicle is None:
                raise ApiError("VEHICLE_NOT_FOUND", 404)
            from app.modules.delivery_users.models import DeliveryProfile

            driver_profile = await self.session.scalar(
                select(DeliveryProfile)
                .where(
                    DeliveryProfile.user_id == row.driver_user_id,
                    DeliveryProfile.merchant_id == self.merchant_id,
                    DeliveryProfile.status == "ACTIVE",
                    DeliveryProfile.approval_status == "APPROVED",
                )
                .with_for_update()
            )
            if driver_profile is None:
                raise ApiError(
                    "DRIVER_UNAVAILABLE", 409, "Assign an active approved driver before loading."
                )
            if await self.session.scalar(
                select(Trip.id)
                .where(
                    Trip.merchant_id == self.merchant_id,
                    (
                        (Trip.vehicle_number == row.vehicle_number)
                        | (Trip.driver_user_id == row.driver_user_id)
                    ),
                    Trip.status.in_(ACTIVE),
                    Trip.id != row.id,
                )
                .limit(1)
            ):
                raise ApiError(
                    "VEHICLE_TRIP_OPEN",
                    409,
                    "Reconcile the vehicle's previous trip before loading it again.",
                )
            if len({l.cylinderType for l in payload.loads}) != len(payload.loads):
                raise ApiError("DUPLICATE_CYLINDER", 422)
            loads = {l.cylinderType: l for l in payload.loads}
            if any(
                code not in loads or loads[code].loadedFilled < values["planned"]
                for code, values in facts.items()
            ):
                raise ApiError(
                    "TRIP_LOAD_SHORT", 422, "Load must cover every planned cylinder allocation."
                )
            if (
                sum(l.loadedFilled + l.openingEmpty for l in payload.loads)
                > config.maxLoadCylinders
            ):
                raise ApiError(
                    "TRIP_LOAD_LIMIT", 422, "Load exceeds the configured cylinder-count ceiling."
                )
            ledger = StockLedger(self.session, self.merchant_id)
            locked = await ledger._locked_items(
                {l.cylinderType: l.loadedFilled for l in payload.loads}, now
            )
            legacy_departure = await self.session.scalar(
                select(DeliverySlip.id)
                .where(
                    DeliverySlip.merchant_id == self.merchant_id,
                    DeliverySlip.vehicle_number == row.vehicle_number,
                    DeliverySlip.status.in_(("DISPATCHED", "ON_LOCATION")),
                )
                .with_for_update()
                .limit(1)
            )
            if legacy_departure:
                raise ApiError(
                    "VEHICLE_ALREADY_OUT",
                    409,
                    "The vehicle has a delivery on the road. Close that dispatch before loading a new trip.",
                )
            from app.modules.deliveries.service import DeliveryService

            committed = await DeliveryService(self.session, self.actor, self.settings)._committed()
            await ledger.check_available(
                {l.cylinderType: l.loadedFilled for l in payload.loads}, committed=committed
            )
            _, empty = await custody(self.session, self.merchant_id)
            for l in payload.loads:
                if locked[l.cylinderType].empty - empty.get(l.cylinderType, 0) < l.openingEmpty:
                    raise ApiError("TRIP_EMPTY_STOCK_SHORT", 409)
                self.session.add(
                    TripLoadLine(
                        trip_id=row.id,
                        cylinder_type=l.cylinderType,
                        merchant_id=self.merchant_id,
                        remaining_filled=l.loadedFilled,
                        current_empty=l.openingEmpty,
                        loaded_filled=l.loadedFilled,
                        opening_empty=l.openingEmpty,
                    )
                )
            row.status = "READY"
        elif payload.action == "DRAFT":
            if not payload.confirmedUnloaded:
                raise ApiError(
                    "TRIP_UNLOAD_CONFIRMATION",
                    422,
                    "Confirm that all trip stock was physically unloaded before releasing vehicle custody.",
                )
            if row.status != "READY":
                raise ApiError("TRIP_STATE_INVALID", 409)
            for line in (
                await self.session.scalars(
                    select(TripLoadLine).where(TripLoadLine.trip_id == row.id)
                )
            ).all():
                await self.session.delete(line)
            row.status = "DRAFT"
            row.route_preview = None
        elif payload.action == "CANCEL":
            if row.status != "DRAFT":
                raise ApiError(
                    "TRIP_STATE_INVALID", 409, "Reset an unstarted loaded trip before cancelling."
                )
            row.notes = (
                (row.notes or "")
                + "\nCancelled planned deliveries: "
                + ", ".join(s.order_number for _, s in pairs)
            )
            for stop, _ in pairs:
                await self.session.delete(stop)
            row.status = "CANCELLED"
        elif payload.action == "START":
            from app.shared.date_time.business_calendar import business_today

            if row.scheduled_date > business_today():
                raise ApiError(
                    "TRIP_DATE_INVALID",
                    409,
                    "A trip cannot start before its scheduled India business date.",
                )
            if row.status != "READY":
                raise ApiError("TRIP_STATE_INVALID", 409, "Only a loaded, ready trip can start.")
            if config.requireOdometer and payload.odometer is None:
                raise ApiError("TRIP_ODOMETER_REQUIRED", 422)
            from app.modules.deliveries.service import DeliveryService

            self.session.info["starting_trip"] = row.id
            try:
                for _, slip in sorted(pairs, key=lambda p: p[1].order_id):
                    await DeliveryService(self.session, self.actor, self.settings).dispatch(
                        slip.id, commit=False
                    )
            finally:
                self.session.info.pop("starting_trip", None)
            row.status = "IN_PROGRESS"
            row.dispatched_at = now
            row.start_odometer = payload.odometer
        elif payload.action == "RETURN":
            if row.status != "IN_PROGRESS" or any(s.status not in SETTLED for _, s in pairs):
                raise ApiError(
                    "TRIP_STOPS_OPEN",
                    409,
                    "Complete or explicitly fail every stop before submitting the vehicle return.",
                )
            if config.requireOdometer and payload.odometer is None:
                raise ApiError("TRIP_ODOMETER_REQUIRED", 422)
            if (
                payload.odometer is not None
                and row.start_odometer is not None
                and payload.odometer < row.start_odometer
            ):
                raise ApiError(
                    "TRIP_ODOMETER_INVALID", 422, "Return odometer cannot precede dispatch reading."
                )
            row.end_odometer = payload.odometer
            self.check_counts(payload.counts, facts)
            row.return_submission = json.dumps(
                {
                    "counts": [l.model_dump() for l in payload.counts],
                    "odometer": payload.odometer,
                    "reason": payload.reason,
                }
            )
            row.return_submitted_by = self.actor.user_id
            row.returned_at = now
            row.status = "RETURNED"
        elif payload.action in ("VERIFY", "RESOLVE"):
            if row.status not in ("RETURNED", "DISCREPANCY"):
                raise ApiError("TRIP_STATE_INVALID", 409)
            if self.actor.user_id == row.driver_user_id or (
                config.requireSeparateReturnVerifier
                and self.actor.user_id == row.return_submitted_by
            ):
                raise ApiError(
                    "SEPARATE_VERIFIER_REQUIRED",
                    403,
                    "Another authorized office user must verify this vehicle return.",
                )
            self.check_counts(payload.counts, facts)
            differences = []
            for line in payload.counts:
                expected = facts[line.cylinderType]
                differences.append(
                    {
                        "cylinderType": line.cylinderType,
                        "filledDifference": line.filled + line.damaged - expected["expectedFilled"],
                        "emptyDifference": line.empty - expected["expectedEmpty"],
                        "damaged": line.damaged,
                    }
                )
            discrepancy = any(
                d["filledDifference"] or d["emptyDifference"] or d["damaged"] for d in differences
            )
            if payload.action == "RESOLVE":
                if row.status != "DISCREPANCY":
                    raise ApiError(
                        "VERIFY_DISCREPANCY_FIRST",
                        409,
                        "Record the office discrepancy before authorizing stock corrections.",
                    )
                await self.resolve_adjustments(row, payload.counts, facts, payload.reason)
            row.verification = json.dumps(
                {
                    "counts": [l.model_dump() for l in payload.counts],
                    "differences": differences,
                    "reason": payload.reason,
                    "adjustmentsApplied": payload.action == "RESOLVE",
                }
            )
            row.verified_by = self.actor.user_id
            row.verified_at = now
            row.status = (
                "DISCREPANCY" if discrepancy and payload.action != "RESOLVE" else "RECONCILED"
            )
            if row.status == "RECONCILED":
                for load in (
                    await self.session.scalars(
                        select(TripLoadLine).where(TripLoadLine.trip_id == row.id).with_for_update()
                    )
                ).all():
                    load.remaining_filled = 0
                    load.current_empty = 0
                    load.active = False
        else:
            raise ApiError("TRIP_ACTION_INVALID", 422)
        self.changed(row, f"Trip {payload.action}: {payload.reason}")
        await self.session.flush()

    def check_counts(self, counts, facts):
        if (
            counts is None
            or len(counts) != len({c.cylinderType for c in counts})
            or {c.cylinderType for c in counts} != set(facts)
        ):
            raise ApiError(
                "TRIP_COUNTS_INVALID",
                422,
                "Supply one actual return count for every trip cylinder type, including zero counts.",
            )

    async def resolve_adjustments(self, row, counts, facts, reason):
        from app.modules.inventory.constants import StockBucket, StockMovementType
        from app.modules.inventory.validation import CheckedMovement

        ledger = StockLedger(self.session, self.merchant_id)
        locked = await ledger._locked_items({c.cylinderType: 0 for c in counts}, datetime.now(UTC))
        for c in counts:
            f = facts[c.cylinderType]
            for bucket, delta in [
                (StockBucket.FILLED, c.filled - f["expectedFilled"]),
                (StockBucket.EMPTY, c.empty - f["expectedEmpty"]),
                (StockBucket.DAMAGED, c.damaged),
            ]:
                if not delta:
                    continue
                target = getattr(locked[c.cylinderType], bucket.value) + delta
                if target < 0:
                    raise ApiError(
                        "TRIP_ADJUSTMENT_NEGATIVE",
                        409,
                        "Return correction would make stock negative.",
                    )
                await ledger.record(
                    CheckedMovement(
                        type=StockMovementType.CORRECTION,
                        bucket=bucket,
                        quantity=None,
                        new_count=target,
                        note=f"Trip {row.id} verified return adjustment: {reason}",
                        reference_id=row.id,
                    ),
                    c.cylinderType,
                    recorded_by_user_id=self.actor.user_id,
                    recorded_by_name=self.actor.display_name,
                )
