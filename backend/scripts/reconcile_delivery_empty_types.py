"""Reconcile proven per-size delivery returns with append-only stock corrections.

Dry-run by default. --apply only repairs delivered slips whose complete per-type
statement agrees with the slip total and whose original empty movements agree in total.
No guessing from allocated cylinders; original movements remain unchanged.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.shared.database.session import AsyncSessionLocal, engine
from app.modules.deliveries.models import DeliverySlip,DeliverySlipItem
from app.modules.inventory.models import StockMovement
from app.modules.merchants.models import Merchant  # noqa: F401 - stock foreign-key metadata
from app.modules.inventory.ledger import StockLedger
from app.modules.inventory.constants import StockBucket,StockMovementType
from app.modules.inventory.validation import CheckedMovement
from app.modules.audit_logs.service import AuditLogService
from app.modules.audit_logs.schemas import AuditLogCreate

PREFIX="EMPTY_TYPE_REPAIR:"


async def reconcile(session, *, apply=False):
    statement=select(DeliverySlip).where(DeliverySlip.status=="DELIVERED").order_by(DeliverySlip.merchant_id,DeliverySlip.id)
    if apply: statement=statement.with_for_update()
    slips=list(await session.scalars(statement))
    plans=[]
    for slip in slips:
        reference=PREFIX+slip.id
        if await session.scalar(select(StockMovement.id).where(StockMovement.merchant_id==slip.merchant_id,StockMovement.reference_id==reference).limit(1)):
            continue
        items=list(await session.scalars(select(DeliverySlipItem).where(DeliverySlipItem.slip_id==slip.id)))
        if not items or any(item.empties_collected is None for item in items): continue
        expected={item.cylinder_type:item.empties_collected for item in items if item.empties_collected}
        if sum(expected.values())!=slip.empties_collected: continue
        booked=defaultdict(int)
        for kind,quantity in (await session.execute(select(StockMovement.cylinder_type,StockMovement.delta_empty).where(
            StockMovement.merchant_id==slip.merchant_id,StockMovement.movement_type=="EMPTIES_COLLECTED",
            StockMovement.reference_id.in_([slip.id,slip.slip_number])))).all():
            booked[kind]+=quantity
        if sum(booked.values())!=slip.empties_collected: continue
        changes={kind:expected.get(kind,0)-booked.get(kind,0) for kind in sorted(expected.keys()|booked.keys()) if expected.get(kind,0)!=booked.get(kind,0)}
        if not changes: continue
        assert sum(changes.values())==0
        plans.append({"slip":slip.slip_number,"order":slip.order_number,"changes":changes})
        if apply:
            now=datetime.now(UTC)
            ledger=StockLedger(session,slip.merchant_id)
            # Stable locking order matches every other stock operation.
            for kind,delta in changes.items():
                item=await ledger._locked_item(kind,now)
                if item.empty+delta<0:
                    raise RuntimeError(f"Cannot reconcile {slip.slip_number}: insufficient recorded empties for {kind}")
                checked=CheckedMovement(type=StockMovementType.CORRECTION,bucket=StockBucket.EMPTY,
                    quantity=None,new_count=item.empty+delta,
                    note=f"Correct per-type empty return allocation for {slip.slip_number}; original movements retained",
                    reference_id=reference)
                await ledger.record(checked,kind,recorded_by_user_id=None,
                    recorded_by_name="System reconciliation",now=now)
            await AuditLogService(session).write_event(AuditLogCreate(event_type="inventory.empty_return_reconciled",
                entity_type="delivery_slip",entity_id=slip.id,result="SUCCESS",
                message=f"Per-type empty inventory corrected for {slip.slip_number}: {json.dumps(changes,separators=(',',':'))}"[:255]))
    if apply: await session.commit()
    return plans


async def main(apply):
    try:
        async with AsyncSessionLocal() as session:
            print(json.dumps({"applied":apply,"repairs":await reconcile(session,apply=apply)},indent=2))
    finally:
        await engine.dispose()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    asyncio.run(main(parser.parse_args().apply))
