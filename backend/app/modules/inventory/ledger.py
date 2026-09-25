"""The only code that changes a stock count (spec §11.3, §18.6).

Everything about the warehouse's integrity is here, and it comes down to one rule: a count and
its movement are written in the same transaction, or neither is. Spec §18.6 puts it as "every
count change is a StockMovement; counts and ledger must always agree", and the only way to keep
that true over years of edits is to leave exactly one door into both tables.

Three things this does that a naive implementation gets wrong:

**Locking.** The row is taken with `SELECT ... FOR UPDATE` before it is read, so two staff
recording a refill for the same cylinder at the same time serialise instead of both reading 120
and both writing 180. Read-then-write without the lock loses one of the two movements' effect
while still writing both ledger rows - the exact disagreement §18.6 forbids.

**Atomicity across lines.** A dispatch checks *every* line before touching *any* count
(spec §10): "fails without touching counts if any line is short". Per-line application would
leave a four-line dispatch half-applied when the last line came up short, with three movements
recorded against a delivery that never left.

**Refusing rather than clamping.** No bucket may go negative (spec §11.3). A negative count is
not a smaller number, it is a warehouse that has lost track of physical objects, so the movement
is refused with the count that is actually there and nothing is written.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.constants import (
    DEFAULT_REORDER_THRESHOLDS,
    MAX_BUCKET_COUNT,
    MovementReference,
    StockBucket,
    StockMovementType,
)
from app.modules.inventory.models import StockItem, StockMovement
from app.modules.inventory.validation import CheckedMovement, invalid
from app.modules.orders.constants import ORDER_LABELS
from app.modules.pricing.constants import CylinderType
from app.shared.exceptions.api_error import ApiError

#: Bucket name -> the model attribute holding it. One mapping, so a new bucket is one line.
_COLUMNS: dict[StockBucket, str] = {
    StockBucket.FILLED: "filled",
    StockBucket.EMPTY: "empty",
    StockBucket.DAMAGED: "damaged",
}


def label_of(cylinder_type: str) -> str:
    """"19 KG". Falls back to the raw code so an unmapped type never renders as blank."""
    try:
        return ORDER_LABELS[CylinderType(cylinder_type)]
    except (KeyError, ValueError):
        return cylinder_type


@dataclass(frozen=True)
class Deltas:
    """Signed changes to the three buckets. Zero means untouched."""

    filled: int = 0
    empty: int = 0
    damaged: int = 0

    def of(self, bucket: StockBucket) -> int:
        return getattr(self, _COLUMNS[bucket])


@dataclass(frozen=True)
class Applied:
    """What one movement did, for the caller to notify on and render.

    `crossed_threshold` is the bit the notification hangs off: it is true only when this
    movement took filled stock from at or above the reorder line to below it. A warning on
    *every* movement while stock is already low would fill the bell and be muted within a day,
    so the alert fires on the crossing rather than on the state.
    """

    movement: StockMovement
    item: StockItem
    crossed_threshold: bool
    emptied: bool


class StockLedger:
    """Applies movements for one merchant. Never commits - the caller owns the transaction."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    # --- What the app posts -----------------------------------------------------------------

    async def record(
        self,
        checked: CheckedMovement,
        cylinder_type: CylinderType,
        *,
        recorded_by_user_id: str | None,
        recorded_by_name: str | None,
        now: datetime | None = None,
    ) -> Applied:
        """Apply one validated manual movement (spec §11.3).

        The quantity of a correction is resolved here rather than in validation, because it is
        the distance between the submitted count and the one on the row - which is not known
        until the row is locked, and would be stale by the time it was written otherwise.
        """
        moment = now or datetime.now(UTC)
        item = await self._locked_item(cylinder_type, moment)

        if checked.type is StockMovementType.CORRECTION:
            deltas, quantity, previous = self._correction_deltas(checked, item)
        else:
            deltas, quantity, previous = self._counted_deltas(checked), checked.quantity, None

        return self._apply(
            item,
            deltas=deltas,
            movement_type=checked.type,
            quantity=int(quantity or 0),
            bucket=checked.bucket,
            previous_count=previous,
            new_count=checked.new_count if checked.type is StockMovementType.CORRECTION else None,
            note=checked.note,
            reference_type=MovementReference.CHALLAN if checked.reference_id else None,
            reference_id=checked.reference_id,
            recorded_by_user_id=recorded_by_user_id,
            recorded_by_name=recorded_by_name,
            moment=moment,
        )

    # --- What the delivery endpoints write --------------------------------------------------

    async def dispatch(
        self,
        lines: dict[CylinderType, int],
        *,
        reference_id: str,
        recorded_by_user_id: str | None,
        recorded_by_name: str | None,
        reference_type: MovementReference = MovementReference.DELIVERY,
        now: datetime | None = None,
    ) -> list[Applied]:
        """Take filled stock out for a delivery slip (spec §10, §18.6). Atomic across lines.

        Every line is locked and checked for sufficiency **before** the first count moves, so a
        short line refuses the whole dispatch and leaves the warehouse exactly as it was. The
        locks are taken in a stable order (by cylinder type) so two dispatches that overlap
        cannot each hold what the other needs.
        """
        moment = now or datetime.now(UTC)
        items = await self._locked_items(lines, moment)

        for cylinder_type, quantity in sorted(lines.items()):
            available = items[cylinder_type].filled
            if available < quantity:
                raise _insufficient(cylinder_type, available=available, needed=quantity)

        return [
            self._apply(
                items[cylinder_type],
                deltas=Deltas(filled=-quantity),
                movement_type=StockMovementType.DISPATCHED,
                quantity=quantity,
                bucket=StockBucket.FILLED,
                previous_count=None,
                new_count=None,
                note=None,
                reference_type=reference_type,
                reference_id=reference_id,
                recorded_by_user_id=recorded_by_user_id,
                recorded_by_name=recorded_by_name,
                moment=moment,
            )
            for cylinder_type, quantity in sorted(lines.items())
        ]

    async def return_filled(
        self,
        lines: dict[CylinderType, int],
        *,
        reference_id: str,
        recorded_by_user_id: str | None,
        recorded_by_name: str | None,
        reference_type: MovementReference = MovementReference.DELIVERY,
        now: datetime | None = None,
    ) -> list[Applied]:
        """Put filled cylinders back after a delivery failed (spec §10 `FAILED`).

        Booked as `RECEIVED_FILLED` against the delivery rather than as a `CORRECTION`, and the
        distinction matters to whoever reconciles the month: a correction says "the register was
        wrong", while this says "these cylinders went out on slip DS-0148 and came back on it".
        The spec's movement types have no dedicated "returned", and inventing one outside
        `StockMovementType` would break the app's filter chips.

        No sufficiency check: it only ever adds.
        """
        moment = now or datetime.now(UTC)
        items = await self._locked_items(lines, moment)
        return [
            self._apply(
                items[cylinder_type],
                deltas=Deltas(filled=quantity),
                movement_type=StockMovementType.RECEIVED_FILLED,
                quantity=quantity,
                bucket=StockBucket.FILLED,
                previous_count=None,
                new_count=None,
                note="Returned undelivered",
                reference_type=reference_type,
                reference_id=reference_id,
                recorded_by_user_id=recorded_by_user_id,
                recorded_by_name=recorded_by_name,
                moment=moment,
            )
            for cylinder_type, quantity in sorted(lines.items())
        ]

    async def collect_empties(
        self,
        lines: dict[CylinderType, int],
        *,
        reference_id: str,
        recorded_by_user_id: str | None,
        recorded_by_name: str | None,
        reference_type: MovementReference = MovementReference.DELIVERY,
        now: datetime | None = None,
    ) -> list[Applied]:
        """Book empties returned by the customer on a confirmed delivery (spec §10).

        No sufficiency check: this only ever adds. Empties that were never collected are
        recorded as `pendingPickup` on the delivery, not as a negative bucket here.
        """
        moment = now or datetime.now(UTC)
        items = await self._locked_items(lines, moment)
        return [
            self._apply(
                items[cylinder_type],
                deltas=Deltas(empty=quantity),
                movement_type=StockMovementType.EMPTIES_COLLECTED,
                quantity=quantity,
                bucket=StockBucket.EMPTY,
                previous_count=None,
                new_count=None,
                note=None,
                reference_type=reference_type,
                reference_id=reference_id,
                recorded_by_user_id=recorded_by_user_id,
                recorded_by_name=recorded_by_name,
                moment=moment,
            )
            for cylinder_type, quantity in sorted(lines.items())
        ]

    # --- Deltas -----------------------------------------------------------------------------

    @staticmethod
    def _counted_deltas(checked: CheckedMovement) -> Deltas:
        quantity = int(checked.quantity or 0)
        if checked.type is StockMovementType.RECEIVED_FILLED:
            return Deltas(filled=quantity)
        if checked.type is StockMovementType.SENT_TO_PLANT:
            # Out of the godown entirely, back to BPCL. One bucket down, nothing up.
            return _minus(checked.bucket, quantity)
        # MARKED_DAMAGED: sideways, out of a working bucket and into damaged. The cylinder is
        # still physically here, which is why the total across buckets does not change.
        return _minus(checked.bucket, quantity, damaged=quantity)

    @staticmethod
    def _correction_deltas(
        checked: CheckedMovement, item: StockItem
    ) -> tuple[Deltas, int, int]:
        """`bucket += (newCount - current)` (spec §11.3), and its audit figures."""
        bucket = checked.bucket
        assert bucket is not None, "validation guarantees a correction names a bucket"
        current = getattr(item, _COLUMNS[bucket])
        change = int(checked.new_count or 0) - current
        if change == 0:
            # Recording a correction that corrects nothing would put a row in the ledger
            # saying a count was audited and left alone, which reads as a change.
            raise invalid("newCount", "no_change", "No change")
        return _bucket_delta(bucket, change), abs(change), current

    # --- Writing ----------------------------------------------------------------------------

    def _apply(
        self,
        item: StockItem,
        *,
        deltas: Deltas,
        movement_type: StockMovementType,
        quantity: int,
        bucket: StockBucket | None,
        previous_count: int | None,
        new_count: int | None,
        note: str | None,
        reference_type: MovementReference | None,
        reference_id: str | None,
        recorded_by_user_id: str | None,
        recorded_by_name: str | None,
        moment: datetime,
    ) -> Applied:
        """Move the counts and write the ledger row. Both, or neither."""
        was_above = item.filled >= item.reorder_threshold
        naive = moment.replace(tzinfo=None)

        for bucket_name, column in _COLUMNS.items():
            change = deltas.of(bucket_name)
            if change == 0:
                continue
            updated = getattr(item, column) + change
            if updated < 0:
                raise _negative(item.cylinder_type, bucket_name, available=getattr(item, column), change=change)
            if updated > MAX_BUCKET_COUNT:
                raise _too_large(item.cylinder_type, bucket_name)
            setattr(item, column, updated)
        item.updated_at = naive

        movement = StockMovement(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            movement_type=movement_type.value,
            cylinder_type=item.cylinder_type,
            quantity=quantity,
            delta_filled=deltas.filled,
            delta_empty=deltas.empty,
            delta_damaged=deltas.damaged,
            bucket=bucket.value if bucket else None,
            previous_count=previous_count,
            new_count=new_count,
            note=note,
            reference_type=reference_type.value if reference_type else None,
            reference_id=reference_id,
            recorded_by_user_id=recorded_by_user_id,
            recorded_by_name=recorded_by_name,
            recorded_at=naive,
        )
        self.session.add(movement)
        return Applied(
            movement=movement,
            item=item,
            # Only a crossing counts, and only downwards: a refill that lands back above the
            # line is not an alert, and a second movement while already low is not a new one.
            crossed_threshold=(
                was_above and item.reorder_threshold > 0 and item.filled < item.reorder_threshold
            ),
            emptied=item.filled == 0 and deltas.filled < 0,
        )

    # --- Rows -------------------------------------------------------------------------------

    async def _locked_items(
        self, lines: dict[CylinderType, int], moment: datetime
    ) -> dict[CylinderType, StockItem]:
        """Lock every line's row up front, in a stable order, to rule out a deadlock."""
        return {
            cylinder_type: await self._locked_item(cylinder_type, moment)
            for cylinder_type in sorted(lines)
        }

    async def _locked_item(self, cylinder_type: CylinderType, moment: datetime) -> StockItem:
        """This merchant's row for the type, locked for update, created if it is the first.

        Creating on demand is what lets a merchant start using the warehouse screen without a
        seeding step, and what lets the snapshot treat "no row" as "never stocked".
        """
        row = await self._select_for_update(cylinder_type)
        if row is not None:
            return row

        row = StockItem(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            cylinder_type=cylinder_type.value,
            filled=0,
            empty=0,
            damaged=0,
            reorder_threshold=DEFAULT_REORDER_THRESHOLDS.get(cylinder_type, 0),
            created_at=moment.replace(tzinfo=None),
            updated_at=moment.replace(tzinfo=None),
        )
        self.session.add(row)
        try:
            # Savepointed, so losing the race to another first movement for the same type
            # does not roll back the caller's whole transaction. Same shape as
            # `orders/numbering.py`, for the same reason.
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            if row in self.session:
                self.session.expunge(row)
            existing = await self._select_for_update(cylinder_type)
            assert existing is not None, "the unique constraint fired, so the row is there"
            return existing
        return row

    async def _select_for_update(self, cylinder_type: CylinderType) -> StockItem | None:
        return await self.session.scalar(
            select(StockItem)
            .where(
                StockItem.merchant_id == self.merchant_id,
                StockItem.cylinder_type == cylinder_type.value,
            )
            .with_for_update()
        )


def _minus(bucket: StockBucket | None, quantity: int, *, damaged: int = 0) -> Deltas:
    assert bucket is not None, "validation guarantees these types name a source bucket"
    out = _bucket_delta(bucket, -quantity)
    if not damaged:
        return out
    return Deltas(filled=out.filled, empty=out.empty, damaged=out.damaged + damaged)


def _bucket_delta(bucket: StockBucket, change: int) -> Deltas:
    return Deltas(**{_COLUMNS[bucket]: change})


def _insufficient(cylinder_type: CylinderType, *, available: int, needed: int) -> ApiError:
    """Spec §10's wording, verbatim - it is shown to the person trying to dispatch."""
    label = label_of(cylinder_type.value)
    return ApiError(
        "INSUFFICIENT_STOCK",
        status.HTTP_409_CONFLICT,
        f"Not enough filled {label} in stock ({available} available, {needed} needed). "
        "Record a refill first.",
        fields=[{"field": cylinder_type.value, "code": "insufficient_stock", "message": f"{available} available"}],
    )


def _negative(cylinder_type: str, bucket: StockBucket, *, available: int, change: int) -> ApiError:
    label = label_of(cylinder_type)
    return ApiError(
        "INSUFFICIENT_STOCK",
        status.HTTP_409_CONFLICT,
        f"Only {available} {bucket.value} {label} in stock, so {abs(change)} cannot be moved out.",
        fields=[{"field": bucket.value, "code": "insufficient_stock", "message": f"{available} available"}],
    )


def _too_large(cylinder_type: str, bucket: StockBucket) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[
            {
                "field": bucket.value,
                "code": "count_too_large",
                "message": f"{label_of(cylinder_type)} {bucket.value} stock cannot exceed {MAX_BUCKET_COUNT}.",
            }
        ],
    )
