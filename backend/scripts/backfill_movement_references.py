"""Make the Warehouse Stock screen readable for movements written before 10 Oct 2026.

`stock_movements.reference_id` is free text and is meant to be read - a challan number on a
refill, a vehicle number on a transfer. Automatic delivery movements put the slip's **uuid**
there, so every such row on the godown screen opened with 36 characters of database key and
pushed the order number off the right edge.

The code no longer does that: a handover now writes the slip number into `reference_id` and
`ORD-… · customer` into `note`. This repairs what was written before.

**Nothing is deleted and no count moves.** A movement is append-only - the counts the app
shows are proved by these rows - so this only rewrites the two fields a person reads. A row
whose `reference_id` is not a uuid was correct when it was written and is left alone; so is
one whose slip has since gone.

    python scripts/backfill_movement_references.py            # dry run
    python scripts/backfill_movement_references.py --execute
"""

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip
from app.modules.inventory.constants import MovementReference
from app.modules.inventory.models import StockMovement
from app.shared.database.session import AsyncSessionLocal

@dataclass(frozen=True)
class _Row:
    """Just what this reads: an id and the reference it carries."""

    id: str
    reference_id: str | None


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
#: Shown when a repair would run long, so a dry run stays readable.
SAMPLE = 8


async def backfill(execute: bool) -> int:
    repaired = 0
    orphaned = 0
    async with AsyncSessionLocal() as db:
        rows = [
            _Row(movement_id, reference)
            for movement_id, reference in (
                await db.execute(
                    select(StockMovement.id, StockMovement.reference_id).where(
                        StockMovement.reference_type == MovementReference.DELIVERY.value
                    )
                )
            ).all()
        ]
        stale = [row for row in rows if row.reference_id and UUID.match(row.reference_id)]
        print(f"Delivery movements : {len(rows)}")
        print(f"Carrying a uuid    : {len(stale)}")
        if not stale:
            print("\nNothing to repair.")
            return 0

        # Four columns, not the whole row: this reads nothing it does not print, so it keeps
        # working against a database the running code is ahead of.
        slips = {
            slip_id: (number, order_number, customer)
            for slip_id, number, order_number, customer in (
                await db.execute(
                    select(
                        DeliverySlip.id,
                        DeliverySlip.slip_number,
                        DeliverySlip.order_number,
                        DeliverySlip.customer_name,
                    ).where(DeliverySlip.id.in_({row.reference_id for row in stale}))
                )
            ).all()
        }

        # One statement per slip, not per row: a round writes a movement per cylinder type and
        # they all carry the same reference. Written as an UPDATE rather than by mutating the
        # rows, so nothing has to flush - a flush sorts every mapped table and needs the whole
        # model registry imported, which a one-off script has no business pulling in.
        seen: set[str] = set()
        for row in stale:
            found = slips.get(row.reference_id)
            if found is None:
                # The slip is gone. Its uuid is the only thing left pointing at what happened,
                # so it stays: an unreadable reference beats none at all.
                orphaned += 1
                continue
            repaired += 1
            if row.reference_id in seen:
                continue
            seen.add(row.reference_id)
            number, order_number, customer = found
            trace = f"{order_number} · {customer}"[:255]
            if len(seen) <= SAMPLE:
                print(f"  {row.reference_id}  ->  {number}  |  {trace}")
            if execute:
                await db.execute(
                    update(StockMovement)
                    .where(
                        StockMovement.reference_type == MovementReference.DELIVERY.value,
                        StockMovement.reference_id == row.reference_id,
                    )
                    .values(reference_id=number, note=trace)
                )

        if len(seen) > SAMPLE:
            print(f"  … and {len(seen) - SAMPLE} more slip(s)")
        print(f"\nTo repair          : {repaired}")
        if orphaned:
            print(f"Slip no longer there: {orphaned} (left as they are)")

        if not execute:
            print("\nDry run. Re-run with --execute to apply.")
            return 0
        await db.commit()
        print(f"\nRepaired {repaired} movement(s). No counts moved and nothing was deleted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Apply the repair.")
    args = parser.parse_args()
    return asyncio.run(backfill(execute=args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
