"""Queue due credit reminders. Safe for cron/systemd timer and overlapping runs."""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.modules.credit.models import CreditReminderState
from app.modules.credit.service import CreditLimitService
from app.modules.customers.models import CustomerProfile
from app.modules.payments.models import Invoice
from app.modules.platform_settings import service as platform_settings
from app.modules.platform_settings.models import SINGLETON_ID, PlatformSettings
from app.shared.database.session import AsyncSessionLocal
from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter, Severity

IST = ZoneInfo("Asia/Kolkata")


def quiet(hour: int, start: int, end: int) -> bool:
    return start <= hour < end if start < end else hour >= start or hour < end


def reminder_due(
    now: datetime,
    *,
    last_sent_at: datetime | None,
    reminder_count: int,
    max_count: int,
    interval_hours: int,
) -> bool:
    if reminder_count >= max_count:
        return False
    return last_sent_at is None or last_sent_at + timedelta(hours=interval_hours) <= now


async def run_once(dry_run: bool = False) -> dict[str, int]:
    report = {"considered": 0, "queued": 0, "resolved": 0, "quiet": 0}
    async with AsyncSessionLocal() as session:
        settings = await platform_settings.load(session)
        await session.flush()
        # One row serializes overlapping cron/timer executions. The second process waits,
        # then reads the reminder state committed by the first and therefore queues nothing
        # twice. This is a transaction lock, so a crash releases it automatically.
        settings = await session.scalar(
            select(PlatformSettings).where(PlatformSettings.id == SINGLETON_ID).with_for_update()
        )
        if not settings.credit_limit_enabled or not settings.credit_reminders_enabled:
            return report
        now = datetime.now(UTC)
        if quiet(
            now.astimezone(IST).hour,
            settings.credit_quiet_start_hour,
            settings.credit_quiet_end_hour,
        ):
            report["quiet"] = 1
            return report
        customers = list(
            await session.scalars(
                select(CustomerProfile).where(
                    CustomerProfile.credit_enabled.is_(True), CustomerProfile.credit_limit > 0
                )
            )
        )
        for customer in customers:
            report["considered"] += 1
            snapshot = await CreditLimitService(session).snapshot(customer.id)
            threshold = snapshot.limit * settings.credit_reminder_threshold_percent / 100
            overdue_before = (
                now - timedelta(days=customer.credit_days) if customer.credit_days else None
            )
            overdue_condition = (
                Invoice.issued_at < overdue_before
                if overdue_before is not None
                else Invoice.due_at < now
            )
            overdue = bool(
                await session.scalar(
                    select(Invoice.id)
                    .where(
                        Invoice.customer_id == customer.id,
                        Invoice.balance > 0,
                        overdue_condition,
                    )
                    .limit(1)
                )
            )
            due = snapshot.used >= threshold or overdue
            state = await session.get(CreditReminderState, customer.id, with_for_update=True)
            if not due:
                if state and state.resolved_at is None:
                    state.resolved_at = state.updated_at = now
                    report["resolved"] += 1
                continue
            if state is None or state.resolved_at is not None:
                state = CreditReminderState(
                    customer_id=customer.id,
                    cycle_started_at=now,
                    last_sent_at=None,
                    reminder_count=0,
                    resolved_at=None,
                    updated_at=now,
                )
                session.add(state)
            if not reminder_due(
                now,
                last_sent_at=state.last_sent_at,
                reminder_count=state.reminder_count,
                max_count=settings.credit_reminder_max_count,
                interval_hours=settings.credit_reminder_interval_hours,
            ):
                continue
            body = settings.credit_reminder_template.format(
                customer_name=customer.name or customer.owner_name or "Customer",
                outstanding=snapshot.used,
                limit=snapshot.limit,
                available=snapshot.available,
            )
            if not dry_run:
                await NotificationOutboxWriter(session).queue_repeatable(
                    NotificationEvent(
                        event_type="CREDIT_REMINDER",
                        recipient_kind="customer",
                        recipient_id=customer.id,
                        recipient_channel="CUSTOMER",
                        entity_type="credit",
                        entity_id=customer.id,
                        title="Credit payment reminder",
                        body=body,
                        severity=Severity.WARNING,
                    )
                )
                state.last_sent_at, state.updated_at = now, now
                state.reminder_count += 1
            report["queued"] += 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(run_once(args.dry_run)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
