"""Pricing reads and writes, and the one place a customer's price is resolved.

`resolve_customer_price` is the point of this module. Order quoting, order creation and the
customer app's "My Pricing" view will all call it rather than reading `pricing_entries`
themselves, so an override can never apply on one screen and not another - the failure the
spec calls out ("quoting, order creation, and pricing display can never disagree").

Tenancy: every read and write starts from the acting merchant. A pricing month or a customer
belonging to another merchant is reported as **404**, never 403, exactly as the customer
routes already do, so ids cannot be probed across tenants.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import CustomerProfile
from app.modules.notifications.events import pricing as pricing_events
from app.modules.pricing import calendar as cal
from app.modules.pricing import validation
from app.modules.pricing.constants import (
    ACTIVE_TIER,
    CLOSED_MONTH_STATUSES,
    CYLINDER_LABELS,
    CylinderType,
    OverrideAction,
    PricingTier,
    cylinders_for,
)
from app.modules.pricing.models import (
    CustomerPriceOverride,
    CustomerPriceOverrideLog,
    PricingChangeLog,
    PricingEntry,
    PricingMonth,
)
from app.modules.pricing.months import PricingMonthProvisioner
from app.modules.pricing.schemas import (
    ChangedBy,
    CustomerPriceItem,
    CustomerPriceOverrideResponse,
    CustomerPricingResponse,
    PriceEntryResponse,
    PricingChangeLogItem,
    PricingChangeLogPage,
    PricingMonthResponse,
    SetCustomerPriceOverrideRequest,
    UpdatePriceEntryRequest,
)
from app.modules.roles.models import Role, RoleLoginChannel
from app.modules.users.role_models import UserRole
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.outbox import NotificationOutboxWriter

#: How a log row's id is presented, per the spec's `PRCLOG-00123`.
LOG_ID_PREFIX = "PRCLOG-"

# The role written onto a log row when the actor holds several. Pricing authority sits with
# these two (the app's own "Pricing changes require the Manager or Accountant role" banner),
# so when one of them is held it is the one the audit line should name.
PREFERRED_LOG_ROLES = ("manager", "accountant")
FALLBACK_LOG_ROLE = "MERCHANT_STAFF"


def _not_found() -> ApiError:
    return ApiError("NOT_FOUND", status.HTTP_404_NOT_FOUND)


# --- The resolution point -------------------------------------------------------------------


async def resolve_customer_price(
    session: AsyncSession,
    customer_id: str,
    cylinder_type: str,
    tier_price: Decimal | None,
) -> Decimal | None:
    """What this customer pays for this cylinder type.

    The customer's own override when one exists, the tier price otherwise. Every caller that
    prices a customer - quote, order creation, billing, the customer's own pricing view -
    goes through here, so there is exactly one answer in the system.
    """
    override = await session.scalar(
        select(CustomerPriceOverride.override_price).where(
            CustomerPriceOverride.customer_id == customer_id,
            CustomerPriceOverride.cylinder_type == cylinder_type,
        )
    )
    return override if override is not None else tier_price


async def tier_prices_for_month(session: AsyncSession, pricing_month_id: str, tier: str) -> dict[str, Decimal]:
    """`{cylinder_type: customer_price}` for one tier of one month."""
    rows = await session.execute(
        select(PricingEntry.cylinder_type, PricingEntry.customer_price).where(
            PricingEntry.pricing_month_id == pricing_month_id,
            PricingEntry.tier == tier,
        )
    )
    return {cylinder_type: price for cylinder_type, price in rows}


# --- Service ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeLogFilters:
    cylinder_type: str | None = None
    tier: str | None = None
    pricing_month_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class PricingService:
    """Everything the two pricing screens do, for one acting merchant staff member."""

    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()

    # --- Months ------------------------------------------------------------------------

    async def months(self) -> list[PricingMonthResponse]:
        """Every month this merchant has, newest first, the current one included.

        Opening the current month is a write, so this commits. It is idempotent: for the
        rest of the month the row is already there and nothing is written.
        """
        await self._current_month()
        months = list(
            await self.session.scalars(
                select(PricingMonth)
                .where(PricingMonth.merchant_id == self.merchant_id)
                .order_by(PricingMonth.month.desc())
            )
        )
        return [await self._month_view(month) for month in months]

    async def update_entry(self, pricing_month_id: str, payload: UpdatePriceEntryRequest) -> PricingMonthResponse:
        """Change one rate, mid-month or not, and log it. One transaction.

        Callable at any point while the month is not ARCHIVED - that is what makes a
        mid-month change possible rather than a month-boundary-only edit.
        """
        today = cal.business_today()
        base_rate = validation.money(payload.bpcl_base_rate, field="bpclBaseRate")
        markup = validation.money(payload.tier_markup, field="tierMarkup", allow_zero=True)
        effective_from = validation.effective_from(payload.effective_from, today=today)

        month = await self._owned_month(pricing_month_id)
        if month.status in CLOSED_MONTH_STATUSES:
            raise ApiError(
                "CONFLICT",
                status.HTTP_409_CONFLICT,
                "This pricing month is closed and can no longer be changed.",
            )
        entry = await self.session.scalar(
            select(PricingEntry).where(
                PricingEntry.pricing_month_id == month.id,
                PricingEntry.cylinder_type == payload.cylinder_type.value,
                PricingEntry.tier == payload.tier.value,
            )
        )
        if entry is None:
            raise _not_found()

        # Read the old values before the update - they are what the log row preserves.
        old_base_rate, old_markup, old_price = entry.bpcl_base_rate, entry.tier_markup, entry.customer_price
        entry.bpcl_base_rate = base_rate
        entry.tier_markup = markup
        now = datetime.now(UTC)
        change_log = PricingChangeLog(
            merchant_id=self.merchant_id,
            pricing_month_id=month.id,
            cylinder_type=entry.cylinder_type,
            tier=entry.tier,
            old_bpcl_base_rate=old_base_rate,
            old_tier_markup=old_markup,
            old_customer_price=old_price,
            new_bpcl_base_rate=base_rate,
            new_tier_markup=markup,
            # Mirrors the generated column. Stored rather than joined, so the log still
            # reads correctly once the entry it describes has moved on.
            new_customer_price=base_rate + markup,
            effective_from=effective_from,
            reason=_clean(payload.reason),
            changed_by_user_id=self.actor.user_id,
            changed_by_name=self.actor.display_name,
            changed_by_role=await self._actor_role(),
            changed_at=now,
        )
        self.session.add(change_log)
        # Flushed so the log row has its id: the notification is keyed on that change, not
        # on the month, because the same cylinder legitimately moves more than once in a
        # month and the outbox collapses repeats of one key.
        await self.session.flush()
        month.updated_by = self.actor.display_name
        month.updated_at = now
        # Staff who are not the one who changed it are quoting customers from what they last
        # saw. A silent change is how somebody is quoted one figure and billed another.
        NotificationOutboxWriter(self.session).queue(
            pricing_events.rate_changed(
                merchant_id=self.merchant_id,
                change_log_id=str(change_log.id),
                cylinder_label=CYLINDER_LABELS[payload.cylinder_type],
                old_price=int(old_price) if old_price is not None else None,
                new_price=int(base_rate + markup),
                changed_by=self.actor.display_name,
                reason=_clean(payload.reason),
            )
        )
        await self.session.commit()
        # `customer_price` is computed by the database, so the row is re-read rather than
        # assumed - the response then shows exactly what was stored.
        await self.session.refresh(entry)
        return await self._month_view(month)

    async def _current_month(self) -> PricingMonth:
        month = await PricingMonthProvisioner(
            self.session, self.merchant_id, self.actor.merchant_code
        ).ensure_current()
        await self.session.commit()
        return month

    async def _owned_month(self, pricing_month_id: str) -> PricingMonth:
        month = await self.session.get(PricingMonth, pricing_month_id)
        if month is None or month.merchant_id != self.merchant_id:
            raise _not_found()
        return month

    async def _month_view(self, month: PricingMonth) -> PricingMonthResponse:
        entries = await self.session.scalars(
            select(PricingEntry)
            .where(PricingEntry.pricing_month_id == month.id, PricingEntry.tier == ACTIVE_TIER.value)
            .order_by(PricingEntry.id)
        )
        return PricingMonthResponse(
            id=month.id,
            month=month.month,
            label=month.label,
            effective_from=month.effective_from,
            effective_to=month.effective_to,
            status=month.status,
            gst_percent=month.gst_percent,
            entries=[
                PriceEntryResponse(
                    cylinder_type=entry.cylinder_type,
                    tier=entry.tier,
                    bpcl_base_rate=entry.bpcl_base_rate,
                    tier_markup=entry.tier_markup,
                    customer_price=entry.customer_price,
                )
                for entry in entries
                # A type that is no longer a known enum value stays in the database but is
                # not offered to the app, which only knows the five it renders.
                if entry.cylinder_type in CylinderType.__members__
            ],
            updated_by=month.updated_by,
            updated_at=month.updated_at,
        )

    # --- Change logs -------------------------------------------------------------------

    async def change_logs(
        self, filters: ChangeLogFilters, *, page: int, page_size: int, offset: int | None = None
    ) -> PricingChangeLogPage:
        statement = select(PricingChangeLog).where(PricingChangeLog.merchant_id == self.merchant_id)
        statement = _apply_log_filters(statement, filters)
        # The count reuses the same filtered statement, so a page and its total can never
        # disagree about scoping.
        total = await self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        skip = offset if offset is not None else (page - 1) * page_size
        rows = await self.session.scalars(
            statement.order_by(PricingChangeLog.changed_at.desc(), PricingChangeLog.id.desc())
            .limit(page_size)
            .offset(skip)
        )
        return PricingChangeLogPage(
            items=[_log_view(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
            limit=page_size,
            offset=skip,
        )

    # --- Per-customer overrides --------------------------------------------------------

    async def customer_pricing(self, customer_id: str) -> CustomerPricingResponse:
        """The Price Setting tab: tier price, override and effective price per cylinder."""
        profile = await self._owned_customer(customer_id)
        return await self._customer_view(profile)

    async def set_override(
        self, customer_id: str, cylinder_type: str, payload: SetCustomerPriceOverrideRequest
    ) -> CustomerPriceItem:
        """Upsert one customer's price for one cylinder type, and log the change."""
        today = cal.business_today()
        kind = _cylinder(cylinder_type)
        price = validation.money(payload.override_price, field="overridePrice")
        effective_from = validation.effective_from(payload.effective_from, today=today)
        reason = _clean(payload.reason)

        profile = await self._owned_customer(customer_id)
        if kind not in cylinders_for(profile.customer_type):
            # The screen does not offer this type for this customer, so accepting a price
            # for it would store an override nothing could ever apply.
            raise _not_found()

        existing = await self._override_of(profile.id, kind)
        now = datetime.now(UTC)
        old_price = existing.override_price if existing else None
        if existing is None:
            self.session.add(
                CustomerPriceOverride(
                    customer_id=profile.id,
                    cylinder_type=kind.value,
                    override_price=price,
                    effective_from=effective_from,
                    reason=reason,
                    set_by_user_id=self.actor.user_id,
                    set_by_name=self.actor.display_name,
                    set_at=now,
                )
            )
        else:
            existing.override_price = price
            existing.effective_from = effective_from
            existing.reason = reason
            existing.set_by_user_id = self.actor.user_id
            existing.set_by_name = self.actor.display_name
            existing.set_at = now
        override_log = await self._override_log(
            profile.id,
            kind,
            action=OverrideAction.SET if existing is None else OverrideAction.UPDATE,
            old_price=old_price,
            new_price=price,
            effective_from=effective_from,
            reason=reason,
            now=now,
        )
        self.session.add(override_log)
        # Flushed for its id; see the note on the rate change above.
        await self.session.flush()
        # The customer should not discover their own rate on an invoice.
        NotificationOutboxWriter(self.session).queue(
            pricing_events.customer_price_set(
                customer_id=profile.id,
                change_log_id=str(override_log.id),
                cylinder_label=CYLINDER_LABELS[kind],
                price=int(price),
                set_by=self.actor.display_name,
                reason=reason,
            )
        )
        await self.session.commit()
        return await self._customer_item(profile, kind)

    async def remove_override(self, customer_id: str, cylinder_type: str) -> CustomerPriceItem:
        """Drop the override; the customer goes back to the tier price. Logged as REMOVE."""
        kind = _cylinder(cylinder_type)
        profile = await self._owned_customer(customer_id)
        existing = await self._override_of(profile.id, kind)
        if existing is None:
            raise _not_found()

        now = datetime.now(UTC)
        old_price = existing.override_price
        await self.session.delete(existing)
        removal_log = await self._override_log(
            profile.id,
            kind,
            action=OverrideAction.REMOVE,
            old_price=old_price,
            new_price=None,
            # The revert takes effect now; this slice schedules nothing.
            effective_from=cal.business_today(),
            reason=None,
            now=now,
        )
        self.session.add(removal_log)
        await self.session.flush()
        _tier, prices = await self._tier_card(profile)
        standard = prices.get(kind.value)
        NotificationOutboxWriter(self.session).queue(
            pricing_events.customer_price_removed(
                customer_id=profile.id,
                change_log_id=str(removal_log.id),
                cylinder_label=CYLINDER_LABELS[kind],
                standard_price=int(standard) if standard is not None else None,
                removed_by=self.actor.display_name,
            )
        )
        await self.session.commit()
        return await self._customer_item(profile, kind)

    async def _owned_customer(self, customer_id: str) -> CustomerProfile:
        profile = await self.session.scalar(select(CustomerProfile).where(CustomerProfile.id == customer_id))
        if profile is None or profile.merchant_id != self.merchant_id:
            raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return profile

    async def _override_of(self, customer_id: str, kind: CylinderType) -> CustomerPriceOverride | None:
        return await self.session.scalar(
            select(CustomerPriceOverride).where(
                CustomerPriceOverride.customer_id == customer_id,
                CustomerPriceOverride.cylinder_type == kind.value,
            )
        )

    async def _override_log(
        self,
        customer_id: str,
        kind: CylinderType,
        *,
        action: OverrideAction,
        old_price: Decimal | None,
        new_price: Decimal | None,
        effective_from: date,
        reason: str | None,
        now: datetime,
    ) -> CustomerPriceOverrideLog:
        return CustomerPriceOverrideLog(
            customer_id=customer_id,
            cylinder_type=kind.value,
            action=action.value,
            old_override_price=old_price,
            new_override_price=new_price,
            effective_from=effective_from,
            reason=reason,
            changed_by_user_id=self.actor.user_id,
            changed_by_name=self.actor.display_name,
            changed_by_role=await self._actor_role(),
            changed_at=now,
        )

    async def _customer_view(self, profile: CustomerProfile) -> CustomerPricingResponse:
        tier, prices = await self._tier_card(profile)
        overrides = {
            row.cylinder_type: row
            for row in await self.session.scalars(
                select(CustomerPriceOverride).where(CustomerPriceOverride.customer_id == profile.id)
            )
        }
        return CustomerPricingResponse(
            customer_id=profile.id,
            tier=tier,
            items=[
                _item_view(kind, prices.get(kind.value), overrides.get(kind.value))
                for kind in cylinders_for(profile.customer_type)
            ],
        )

    async def _customer_item(self, profile: CustomerProfile, kind: CylinderType) -> CustomerPriceItem:
        _tier, prices = await self._tier_card(profile)
        return _item_view(kind, prices.get(kind.value), await self._override_of(profile.id, kind))

    async def _tier_card(self, profile: CustomerProfile) -> tuple[str, dict[str, Decimal]]:
        """This customer's tier, and the current month's prices for it.

        The tier comes from the customer's own `pricing_tier`, but only STANDARD is
        populated today, so a tier with no rates falls back to the STANDARD card rather
        than pricing the customer at nothing.
        """
        month = await self._current_month()
        tier = (profile.pricing_tier or ACTIVE_TIER.value).upper()
        prices = await tier_prices_for_month(self.session, month.id, tier)
        if not prices and tier != ACTIVE_TIER.value:
            prices = await tier_prices_for_month(self.session, month.id, ACTIVE_TIER.value)
        return tier, prices

    async def _actor_role(self) -> str:
        """The role name written onto a log row, from the session's user - never the body."""
        codes = set(
            await self.session.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .join(RoleLoginChannel, RoleLoginChannel.role_id == Role.id)
                .where(
                    UserRole.user_id == self.actor.user_id,
                    UserRole.is_active.is_(True),
                    Role.is_active.is_(True),
                    RoleLoginChannel.login_channel == LoginChannel.MERCHANT.value,
                    RoleLoginChannel.is_allowed.is_(True),
                )
            )
        )
        for preferred in PREFERRED_LOG_ROLES:
            if preferred in codes:
                return preferred.upper()
        if codes:
            return min(codes).upper()
        return (self.actor.staff_type or FALLBACK_LOG_ROLE).upper()


# --- Views -----------------------------------------------------------------------------------


def _item_view(
    kind: CylinderType, tier_price: Decimal | None, override: CustomerPriceOverride | None
) -> CustomerPriceItem:
    return CustomerPriceItem(
        cylinder_type=kind,
        cylinder_label=CYLINDER_LABELS[kind],
        tier_price=tier_price,
        override=(
            CustomerPriceOverrideResponse(
                override_price=override.override_price,
                effective_from=override.effective_from,
                reason=override.reason,
                set_by=override.set_by_name,
                set_at=override.set_at,
            )
            if override is not None
            else None
        ),
        # The same rule `resolve_customer_price` applies, so this screen and the invoice
        # cannot show different numbers.
        effective_price=override.override_price if override is not None else tier_price,
    )


def _log_view(row: PricingChangeLog) -> PricingChangeLogItem:
    return PricingChangeLogItem(
        id=f"{LOG_ID_PREFIX}{row.id:05d}",
        pricing_month_id=row.pricing_month_id,
        cylinder_type=row.cylinder_type,
        tier=row.tier,
        old_bpcl_base_rate=row.old_bpcl_base_rate,
        old_tier_markup=row.old_tier_markup,
        old_customer_price=row.old_customer_price,
        new_bpcl_base_rate=row.new_bpcl_base_rate,
        new_tier_markup=row.new_tier_markup,
        new_customer_price=row.new_customer_price,
        effective_from=row.effective_from,
        reason=row.reason,
        changed_by=ChangedBy(id=row.changed_by_user_id, name=row.changed_by_name, role=row.changed_by_role),
        changed_at=row.changed_at,
    )


def _apply_log_filters(statement: Select, filters: ChangeLogFilters) -> Select:
    if filters.cylinder_type:
        statement = statement.where(PricingChangeLog.cylinder_type == _cylinder(filters.cylinder_type).value)
    if filters.tier:
        statement = statement.where(PricingChangeLog.tier == _tier(filters.tier).value)
    if filters.pricing_month_id:
        statement = statement.where(PricingChangeLog.pricing_month_id == filters.pricing_month_id)
    if filters.date_from:
        statement = statement.where(PricingChangeLog.effective_from >= filters.date_from)
    if filters.date_to:
        statement = statement.where(PricingChangeLog.effective_from <= filters.date_to)
    return statement


def _cylinder(value: str) -> CylinderType:
    """Parse a cylinder type from a path or query parameter, or 422."""
    try:
        return CylinderType(str(value).upper())
    except ValueError as error:
        raise _unknown_value("cylinderType", "unknown_cylinder_type", CylinderType) from error


def _tier(value: str) -> PricingTier:
    try:
        return PricingTier(str(value).upper())
    except ValueError as error:
        raise _unknown_value("tier", "unknown_tier", PricingTier) from error


def _unknown_value(field: str, code: str, choices) -> ApiError:
    allowed = ", ".join(member.value for member in choices)
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": f"Use one of {allowed}."}],
    )


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None
