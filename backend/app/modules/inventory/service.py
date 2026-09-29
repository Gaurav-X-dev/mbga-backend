"""Warehouse reads and writes (spec §11).

Only one actor reaches these routes: merchant staff holding `inventory.view` or
`inventory.adjust`. There is no customer-facing warehouse - a customer sees whether their order
can be delivered, not how many cylinders are in the godown - so the tenancy rule is simple and
absolute: every query and every write is pinned to `actor.require_merchant_id()`, and another
merchant's stock is not visible at all rather than being refused when asked for.

What this layer does *not* do is arithmetic. Counts only ever change in `ledger.py`, so the
service composes: validate the body, hand it to the ledger, notify if a threshold was crossed,
commit once. Keeping the sums out of here is what makes "counts and ledger always agree"
(spec §18.6) a property of one file rather than a habit spread across three.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory import validation
from app.modules.inventory.alerts import derive
from app.modules.inventory.constants import (
    ALL_CYLINDERS,
    DEFAULT_MOVEMENT_LIMIT,
    DEFAULT_REORDER_THRESHOLDS,
    MAX_MOVEMENT_LIMIT,
    MovementReference,
    StockMovementType,
)
from app.modules.inventory.ledger import Applied, StockLedger, label_of
from app.modules.inventory.models import StockItem, StockMovement
from app.modules.inventory.schemas import (
    InventorySnapshotResponse,
    MovementDeltas,
    RecordStockMovementRequest,
    StockAlertResponse,
    StockItemResponse,
    StockMovementResponse,
)
from app.modules.notifications.events import stock as stock_events
from app.modules.pricing.constants import CylinderType
from app.shared.business.actor import BusinessActor
from app.shared.idempotency.service import IdempotencyService, validate_key
from app.shared.notifications.outbox import NotificationOutboxWriter

#: Operation name under which a movement's `Idempotency-Key` is held. Spec §1 lists
#: `POST /inventory/movements` as idempotent, and the reason is the same as for orders: a
#: godown phone on patchy wifi that retries must not book the refill truck twice.
IDEMPOTENT_RECORD = "inventory.record_movement"


@dataclass
class MovementFilters:
    """Spec §11.2's query: one cylinder type or `ALL`, and how many rows."""

    cylinder_type: str | None = None
    limit: int | None = None


class InventoryService:
    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()
        self.notifications = NotificationOutboxWriter(session)

    # --- Reads ------------------------------------------------------------------------------

    async def snapshot(self, *, now: datetime | None = None) -> InventorySnapshotResponse:
        """The Warehouse Stock screen and the dashboard's stock card (spec §11.1).

        Every cylinder type is returned whether or not the merchant has ever stocked it, so the
        card grid on the screen has a fixed shape and the app needs no placeholder logic.

        Alerts come only from types that have a row - that is, types this merchant has actually
        handled. A brand-new merchant is at zero for all five, and reporting five critical
        shortages before they have recorded a single cylinder would be technically true and
        operationally useless: a cylinder they do not carry has not run out.
        """
        rows = {row.cylinder_type: row for row in await self._items()}
        items = [_item_view(cylinder_type, rows.get(cylinder_type.value)) for cylinder_type in CylinderType]
        alerts = derive([(row, label_of(row.cylinder_type)) for row in rows.values()])
        return InventorySnapshotResponse(
            items=items,
            alerts=[
                StockAlertResponse(
                    id=alert.id,
                    cylinder_type=alert.cylinder_type,
                    severity=alert.severity,
                    message=alert.message,
                )
                for alert in alerts
            ],
            as_of=now or datetime.now(UTC),
        )

    async def movements(self, filters: MovementFilters) -> list[StockMovementResponse]:
        """The history under the cards, newest first (spec §11.2).

        `recorded_at` is stored with microsecond precision, so movements recorded seconds apart
        keep their sequence. The id breaks the remaining tie: the lines of a single dispatch
        genuinely share one instant, and a stable order beats an arbitrary one.
        """
        statement = self._scope(select(StockMovement)).order_by(
            StockMovement.recorded_at.desc(), StockMovement.id.desc()
        )
        statement = self._apply_cylinder(statement, filters.cylinder_type)
        rows = list(await self.session.scalars(statement.limit(_limit(filters.limit))))
        return [_movement_view(row) for row in rows]

    # --- Writes -----------------------------------------------------------------------------

    async def record_with_idempotency(
        self, payload: RecordStockMovementRequest, idempotency_key: str | None
    ) -> StockMovementResponse:
        """Record a movement, honouring `Idempotency-Key` when the client sends one.

        A replay re-reads the stored movement rather than replaying the old response body, so
        the caller always sees the ledger as it is now. With no key this is a plain write - the
        header is optional, and a client that omits it is not punished for it.
        """
        key = validate_key(idempotency_key)
        if key is None:
            return await self.record(payload)

        idempotency = IdempotencyService(self.session)
        record, replay = await idempotency.begin(
            actor=self.actor,
            operation=IDEMPOTENT_RECORD,
            key=key,
            payload=payload.model_dump(mode="json", by_alias=True),
        )
        if replay is not None:
            if replay.result_reference:
                stored = await self._movement(replay.result_reference)
                if stored is not None:
                    return _movement_view(stored)
            # Completed without a readable movement: nothing is on the ledger under this key,
            # so the retry proceeds rather than being told a phantom movement exists.
            return await self.record(payload)

        try:
            movement = await self.record(payload)
        except Exception as error:
            # Released as FAILED so a corrected retry is not blocked by the rejected attempt.
            # Committed on its own, because the movement's transaction has already rolled back.
            await idempotency.fail(record, failure_code=getattr(error, "code", "ERROR"))
            await self.session.commit()
            raise
        await idempotency.complete(record, response_status=201, result_reference=movement.id)
        await self.session.commit()
        return movement

    async def record(self, payload: RecordStockMovementRequest) -> StockMovementResponse:
        """Apply one movement (spec §11.3). One transaction.

        The order is deliberate: validate first so a malformed body locks nothing, then apply
        under the row lock, then queue any notification, then commit once. The notification is
        written to the outbox inside this transaction, so a movement that rolls back cannot
        leave a "stock is low" message behind for a shortage that never happened.
        """
        checked = validation.validate(payload)
        ledger = StockLedger(self.session, self.merchant_id)
        applied = await ledger.record(
            checked,
            payload.cylinder_type,
            recorded_by_user_id=self.actor.user_id,
            recorded_by_name=self.actor.display_name,
        )
        self._notify(applied)
        await self.session.commit()
        return _movement_view(applied.movement)

    def _notify(self, applied: Applied) -> None:
        """Tell staff when this movement took stock below the line (spec §18.8).

        On the **crossing**, not on the state. A warning every time a movement happens while
        stock is already low would be muted inside a day, and then the one that mattered would
        be muted too. Keyed on the movement id so the same cylinder can warn again next month
        without colliding with this month's row on the outbox's uniqueness constraint.
        """
        item = applied.item
        label = label_of(item.cylinder_type)
        if applied.emptied:
            self.notifications.queue(
                stock_events.out_of_stock(
                    self.merchant_id, item.cylinder_type, label, movement_id=applied.movement.id
                )
            )
        elif applied.crossed_threshold:
            self.notifications.queue(
                stock_events.below_threshold(
                    self.merchant_id,
                    item.cylinder_type,
                    label,
                    item.filled,
                    item.reorder_threshold,
                    movement_id=applied.movement.id,
                )
            )

    # --- Scoping ----------------------------------------------------------------------------

    def _scope(self, statement: Select) -> Select:
        """Every warehouse query starts here. Applied as a `WHERE`, never as a later filter."""
        return statement.where(StockMovement.merchant_id == self.merchant_id)

    async def _items(self) -> list[StockItem]:
        return list(
            await self.session.scalars(
                select(StockItem).where(StockItem.merchant_id == self.merchant_id)
            )
        )

    async def _movement(self, movement_id: str) -> StockMovement | None:
        return await self.session.scalar(
            self._scope(select(StockMovement)).where(StockMovement.id == movement_id)
        )

    @staticmethod
    def _apply_cylinder(statement: Select, value: str | None) -> Select:
        """`cylinderType = <code> | ALL` (spec §11.2).

        An unknown code returns nothing rather than 422: the filter is a chip on a screen, and
        a stale chip should show an empty history, not an error dialog.
        """
        if not value or value.upper() == ALL_CYLINDERS:
            return statement
        return statement.where(StockMovement.cylinder_type == value)


def _limit(value: int | None) -> int:
    if value is None or value < 1:
        return DEFAULT_MOVEMENT_LIMIT
    return min(value, MAX_MOVEMENT_LIMIT)


def _item_view(cylinder_type: CylinderType, row: StockItem | None) -> StockItemResponse:
    """One card. A type never stocked reads as zeros against its default threshold."""
    if row is None:
        return StockItemResponse(
            cylinder_type=cylinder_type,
            cylinder_label=label_of(cylinder_type.value),
            filled=0,
            empty=0,
            damaged=0,
            reorder_threshold=DEFAULT_REORDER_THRESHOLDS.get(cylinder_type, 0),
            updated_at=None,
        )
    return StockItemResponse(
        cylinder_type=cylinder_type,
        cylinder_label=label_of(row.cylinder_type),
        filled=row.filled,
        empty=row.empty,
        damaged=row.damaged,
        reorder_threshold=row.reorder_threshold,
        updated_at=row.updated_at,
    )


def _movement_view(row: StockMovement) -> StockMovementResponse:
    return StockMovementResponse(
        id=row.id,
        type=StockMovementType(row.movement_type),
        cylinder_type=CylinderType(row.cylinder_type),
        cylinder_label=label_of(row.cylinder_type),
        quantity=row.quantity,
        deltas=MovementDeltas(
            # Omitted where the bucket was untouched, matching the spec's payloads.
            filled=row.delta_filled or None,
            empty=row.delta_empty or None,
            damaged=row.delta_damaged or None,
        ),
        note=row.note,
        reference_type=MovementReference(row.reference_type) if row.reference_type else None,
        reference_id=row.reference_id,
        recorded_by=row.recorded_by_name,
        recorded_at=row.recorded_at,
    )
