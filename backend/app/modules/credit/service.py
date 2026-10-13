"""Server-side trade-credit calculation and enforcement."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credit.models import CreditOverrideAudit
from app.modules.customers.models import CustomerProfile
from app.modules.orders.constants import OrderStatus
from app.modules.orders.models import Order
from app.modules.payments.models import Invoice
from app.modules.platform_settings import service as platform_settings
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.models import NotificationOutbox
from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter, Severity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreditSnapshot:
    customer_id: str
    enabled: bool
    limit: int
    used: int
    available: int
    proposed_amount: int = 0

    @property
    def exceeds(self) -> bool:
        return self.enabled and self.used + self.proposed_amount > self.limit


def blocked_message(snapshot: CreditSnapshot) -> str:
    return (
        f"Credit limit reached. Used: ₹{snapshot.used} of ₹{snapshot.limit}. "
        f"Available: ₹{snapshot.available}. "
        "Please pay your outstanding amount to place a new order."
    )


class CreditLimitService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(
        self,
        customer_id: str,
        *,
        proposed_amount: int = 0,
        replacing_order_id: str | None = None,
        lock: bool = False,
        include_disabled_usage: bool = False,
    ) -> CreditSnapshot:
        query = select(CustomerProfile).where(CustomerProfile.id == customer_id)
        if lock:
            query = query.with_for_update()
        customer = await self.session.scalar(query)
        if customer is None:
            raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)

        settings = await platform_settings.load(self.session)
        enabled = bool(
            settings.credit_limit_enabled
            and customer.credit_enabled
            and int(customer.credit_limit or 0) > 0
        )
        if not enabled and not include_disabled_usage:
            return CreditSnapshot(
                customer.id,
                False,
                int(customer.credit_limit or 0),
                0,
                int(customer.credit_limit or 0),
                proposed_amount,
            )

        # These must be locking/current reads. Under MySQL REPEATABLE READ a request may
        # have established its snapshot before it waited for the customer row; a normal
        # aggregate could then miss the order committed by the request ahead of it.
        invoice_balances = await self.session.scalars(
            select(Invoice.balance)
            .where(Invoice.customer_id == customer.id, Invoice.balance > 0)
            .with_for_update()
        )
        invoiced = sum(int(balance or 0) for balance in invoice_balances)
        pending_query = select(Order.total_amount).where(
            Order.customer_id == customer.id,
            Order.invoice_id.is_(None),
            Order.status.not_in((OrderStatus.CANCELLED.value, OrderStatus.DELIVERED.value)),
        )
        if replacing_order_id:
            pending_query = pending_query.where(Order.id != replacing_order_id)
        pending_amounts = await self.session.scalars(pending_query.with_for_update())
        pending = sum(int(amount or 0) for amount in pending_amounts)
        used = invoiced + pending
        limit = int(customer.credit_limit or 0)
        return CreditSnapshot(
            customer.id, enabled, limit, used, max(limit - used, 0), int(proposed_amount)
        )

    async def enforce(
        self,
        customer_id: str,
        proposed_amount: int,
        *,
        replacing_order_id: str | None = None,
    ) -> CreditSnapshot:
        snapshot = await self.snapshot(
            customer_id,
            proposed_amount=proposed_amount,
            replacing_order_id=replacing_order_id,
            lock=True,
        )
        if not snapshot.exceeds:
            return snapshot
        override = await self.session.scalar(
            select(CreditOverrideAudit)
            .where(
                CreditOverrideAudit.customer_id == customer_id,
                CreditOverrideAudit.consumed_at.is_(None),
                CreditOverrideAudit.expires_at > datetime.now(UTC),
                CreditOverrideAudit.amount >= proposed_amount,
            )
            .order_by(CreditOverrideAudit.created_at)
            .with_for_update()
        )
        if override is not None:
            override.consumed_at = datetime.now(UTC)
            await self.session.flush()
            return snapshot
        try:
            await self._queue_blocked(snapshot)
            # This endpoint is about to return an error and has not written the order. Commit
            # only the durable outbox row; Firebase delivery happens later in the worker.
            await self.session.commit()
        except Exception:
            # Notification persistence is best-effort. It must never turn a valid credit
            # refusal into either a 500 or an accepted order.
            logger.exception(
                "Could not queue credit-block notification for customer_id=%s",
                customer_id,
            )
            await self.session.rollback()
        raise ApiError(
            "ORDER_NOT_ALLOWED",
            status.HTTP_409_CONFLICT,
            blocked_message(snapshot),
        )

    async def enforce_fail_open(
        self,
        customer_id: str,
        proposed_amount: int,
        *,
        replacing_order_id: str | None = None,
    ) -> CreditSnapshot | None:
        try:
            return await self.enforce(
                customer_id,
                proposed_amount,
                replacing_order_id=replacing_order_id,
            )
        except ApiError as error:
            # A deliberate limit refusal must reach the app. Any other error raised while
            # resolving credit data is a credit-feature failure and therefore fails open.
            if error.code == "ORDER_NOT_ALLOWED":
                raise
            logger.exception("Credit check failed open for customer_id=%s", customer_id)
            return None
        except Exception:
            logger.exception("Credit check failed open for customer_id=%s", customer_id)
            return None

    async def _queue_blocked(self, snapshot: CreditSnapshot) -> None:
        settings = await platform_settings.load(self.session)
        cutoff = datetime.now(UTC) - timedelta(
            minutes=max(int(settings.credit_block_push_cooldown_minutes or 60), 1)
        )
        recent = await self.session.scalar(
            select(NotificationOutbox.id).where(
                NotificationOutbox.event_type == "CREDIT_LIMIT_BLOCKED",
                NotificationOutbox.recipient_id == snapshot.customer_id,
                NotificationOutbox.created_at >= cutoff,
            )
        )
        if recent:
            return
        await NotificationOutboxWriter(self.session).queue_repeatable(
            NotificationEvent(
                event_type="CREDIT_LIMIT_BLOCKED",
                recipient_kind="customer",
                recipient_id=snapshot.customer_id,
                recipient_channel="CUSTOMER",
                entity_type="credit",
                entity_id=snapshot.customer_id,
                title="Credit limit reached",
                body=blocked_message(snapshot) + " Open Payments to clear your balance.",
                severity=Severity.WARNING,
            )
        )
