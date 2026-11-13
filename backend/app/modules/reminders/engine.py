"""One scheduler for proximity, visit, inactivity and pricing reminders."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select

from app.modules.authentication.constants import LoginChannel
from app.modules.business_catalogue.models import CylinderTypeDefinition
from app.modules.customers.models import (
    CustomerDeliverySite,
    CustomerProfile,
    CustomerReportMembership,
)
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.orders.models import Order
from app.modules.pricing.models import PricingEntry, PricingMonth
from app.modules.reminders.models import PricingReview, Reminder
from app.modules.reminders.policies import effective_rules
from app.modules.users.models import User
from app.modules.users.role_repository import UserRoleRepository
from app.shared.date_time.business_calendar import IST_TIMEZONE
from app.shared.geo.distance import haversine_metres
from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def in_window(rule, now):
    local = now.astimezone(IST_TIMEZONE)
    hour_ok = (
        rule.startHour <= local.hour < rule.endHour
        if rule.startHour < rule.endHour
        else local.hour >= rule.startHour or local.hour < rule.endHour
    )
    return local.weekday() in rule.weekdays and hour_ok


def elapsed(now, previous):
    return max(
        0,
        (now.astimezone(IST_TIMEZONE).date() - utc(previous).astimezone(IST_TIMEZONE).date()).days,
    )


@dataclass
class Candidate:
    kind: str
    subject: str
    baseline: str
    context: dict
    customer_id: str | None = None
    site_id: str | None = None
    assigned_user_id: str | None = None

    def fingerprint(self, merchant_id):
        return hashlib.sha256(
            json.dumps(
                [
                    merchant_id,
                    self.kind,
                    self.customer_id,
                    self.site_id,
                    self.assigned_user_id,
                    self.baseline,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class ReminderEngine:
    def __init__(self, session, now=None):
        self.session = session
        self.now = now or datetime.now(UTC)
        self.permissions = UserRoleRepository(session)
        self.stats = {"considered": 0, "queued": 0, "resolved": 0, "skipped": 0}

    async def recipients(self, merchant_id, rule, kind):
        pairs = (
            (
                await self.session.execute(
                    select(MerchantUser.user_id)
                    .join(User, User.id == MerchantUser.user_id)
                    .where(
                        MerchantUser.merchant_id == merchant_id,
                        MerchantUser.status == "ACTIVE",
                        User.status == "ACTIVE",
                    )
                )
            )
            .scalars()
            .all()
        )
        eligible = []
        for user_id in pairs:
            if rule.staffUserIds and user_id not in rule.staffUserIds:
                continue
            permissions = await self.permissions.get_effective_permissions(
                user_id=user_id, login_channel=LoginChannel.MERCHANT, now=self.now
            )
            required = "pricing.manage" if kind == "PRICING" else "customers.view"
            if required in permissions:
                eligible.append(user_id)
        return eligible

    async def candidates(self, merchant, rules):
        if not any(rules[kind].enabled for kind in ("PROXIMITY", "INACTIVE")):
            return (
                await self.pricing_candidates(merchant, rules["PRICING"])
                if rules["PRICING"].enabled
                else []
            )
        customers = (
            await self.session.scalars(
                select(CustomerProfile).where(
                    CustomerProfile.merchant_id == merchant.id, CustomerProfile.status == "APPROVED"
                )
            )
        ).all()
        groups = dict(
            (
                await self.session.execute(
                    select(CustomerReportMembership.customer_id, CustomerReportMembership.group_id)
                    .join(
                        CustomerProfile, CustomerProfile.id == CustomerReportMembership.customer_id
                    )
                    .where(CustomerProfile.merchant_id == merchant.id)
                )
            ).all()
        )
        activity = {
            cid: utc(moment)
            for cid, moment in (
                await self.session.execute(
                    select(Order.customer_id, func.max(Order.placed_at))
                    .where(Order.merchant_id == merchant.id, Order.status != "CANCELLED")
                    .group_by(Order.customer_id)
                )
            ).all()
        }
        active = set(
            (
                await self.session.scalars(
                    select(Order.customer_id)
                    .where(
                        Order.merchant_id == merchant.id,
                        Order.status.in_(
                            ["PLACED", "CONFIRMED", "OUT_FOR_DELIVERY", "ON_LOCATION"]
                        ),
                    )
                    .distinct()
                )
            ).all()
        )
        sites = {}
        drivers = []
        if rules["PROXIMITY"].enabled:
            for site in (
                await self.session.scalars(
                    select(CustomerDeliverySite)
                    .join(CustomerProfile, CustomerProfile.id == CustomerDeliverySite.customer_id)
                    .where(
                        CustomerProfile.merchant_id == merchant.id,
                        CustomerDeliverySite.is_active.is_(True),
                    )
                )
            ).all():
                sites.setdefault(site.customer_id, []).append(site)
            drivers = (
                await self.session.scalars(
                    select(DeliveryProfile)
                    .join(User, User.id == DeliveryProfile.user_id)
                    .where(
                        DeliveryProfile.merchant_id == merchant.id,
                        DeliveryProfile.status == "ACTIVE",
                        DeliveryProfile.approval_status == "APPROVED",
                        DeliveryProfile.on_duty.is_(True),
                        User.status == "ACTIVE",
                    )
                )
            ).all()
        candidates = []
        for kind in ("INACTIVE", "PROXIMITY"):
            rule = rules[kind]
            if not rule.enabled:
                continue
            for customer in customers:
                if rule.customerTypes and customer.customer_type not in rule.customerTypes:
                    continue
                if rule.groupIds and groups.get(customer.id) not in rule.groupIds:
                    continue
                if rule.suppressActiveOrders and customer.id in active:
                    continue
                latest = activity.get(customer.id)
                if (
                    latest is None
                    and not rule.includeNeverOrdered
                    and not (kind == "PROXIMITY" and rule.days == 0)
                ):
                    continue
                anchor = latest or utc(
                    customer.approved_at or customer.registered_at or customer.created_at
                )
                days = elapsed(self.now, anchor)
                if days < rule.days:
                    continue
                name = customer.name or customer.owner_name or "Customer"
                context = {
                    "customer_name": name,
                    "merchant_name": merchant.name,
                    "days": days,
                    "month": "",
                    "distance_km": "",
                    "reason": f"No order for {days} days.",
                    "baseline": anchor.isoformat(),
                }
                if kind == "INACTIVE":
                    candidates.append(
                        Candidate(kind, name, anchor.isoformat(), context, customer.id)
                    )
                    continue
                closest = None
                for site in sites.get(customer.id) or [None]:
                    latitude = site.latitude if site else customer.address_latitude
                    longitude = site.longitude if site else customer.address_longitude
                    if latitude is None or longitude is None:
                        self.stats["skipped"] += 1
                        continue
                    for driver in drivers:
                        if (
                            not driver.last_ping_at
                            or not 0
                            <= (self.now - utc(driver.last_ping_at)).total_seconds()
                            <= rule.maxLocationAgeSeconds
                        ):
                            continue
                        if (
                            driver.location_accuracy is None
                            or not 0 <= float(driver.location_accuracy) <= rule.maxAccuracyMeters
                        ):
                            continue
                        if driver.current_latitude is None or driver.current_longitude is None:
                            continue
                        if (
                            abs(float(latitude) - float(driver.current_latitude))
                            > rule.radiusMeters / 110000
                        ):
                            continue
                        distance = haversine_metres(
                            float(latitude),
                            float(longitude),
                            float(driver.current_latitude),
                            float(driver.current_longitude),
                        )
                        if distance <= rule.radiusMeters and (
                            closest is None or distance < closest
                        ):
                            closest = distance
                if closest is not None:
                    context.update(
                        distance_km=round(closest / 1000, 2),
                        reason="A delivery partner is near your location. Open the app to place an order.",
                    )
                    candidates.append(
                        Candidate(kind, name, anchor.isoformat(), context, customer.id)
                    )
        if rules["PRICING"].enabled:
            candidates.extend(await self.pricing_candidates(merchant, rules["PRICING"]))
        return candidates

    async def pricing_candidates(self, merchant, rule):
        local = self.now.astimezone(IST_TIMEZONE).date()
        next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
        periods = [local.strftime("%Y-%m")]
        if rule.upcomingDays and (next_month - local).days <= rule.upcomingDays:
            periods.append(next_month.strftime("%Y-%m"))
        cylinders = set(
            (
                await self.session.scalars(
                    select(CylinderTypeDefinition.code).where(
                        CylinderTypeDefinition.is_active.is_(True)
                    )
                )
            ).all()
        )
        tiers = set(
            (
                await self.session.scalars(
                    select(CustomerProfile.pricing_tier)
                    .where(
                        CustomerProfile.merchant_id == merchant.id,
                        CustomerProfile.status == "APPROVED",
                    )
                    .distinct()
                )
            ).all()
        )
        if not tiers:
            from app.modules.pricing.constants import PricingTier

            tiers = {PricingTier.STANDARD.value}
        result = []
        for month in periods:
            card = await self.session.scalar(
                select(PricingMonth).where(
                    PricingMonth.merchant_id == merchant.id, PricingMonth.month == month
                )
            )
            review = await self.session.scalar(
                select(func.max(PricingReview.reviewed_at)).where(
                    PricingReview.merchant_id == merchant.id, PricingReview.month == month
                )
            )
            entries = (
                (
                    await self.session.execute(
                        select(PricingEntry.cylinder_type, PricingEntry.tier).where(
                            PricingEntry.pricing_month_id == card.id,
                            PricingEntry.customer_price > 0,
                        )
                    )
                ).all()
                if card
                else []
            )
            present = set(entries)
            missing = sorted((c, t) for c in cylinders for t in tiers if (c, t) not in present)
            baseline = utc(review).isoformat() if review else month
            if rule.missingRates:
                for cylinder, tier in missing:
                    context = {
                        "customer_name": "",
                        "merchant_name": merchant.name,
                        "days": 0,
                        "distance_km": "",
                        "month": month,
                        "reason": f"Missing {cylinder} / {tier} pricing.",
                        "cylinder": cylinder,
                        "tier": tier,
                        "trigger": "MISSING",
                    }
                    result.append(
                        Candidate(
                            "PRICING",
                            f"{month} {cylinder} {tier}",
                            f"{month}:{cylinder}:{tier}",
                            context,
                        )
                    )
            start = datetime.combine(local.replace(day=1), time.min, IST_TIMEZONE).astimezone(UTC)
            age = elapsed(self.now, utc(review) if review else start)
            if rule.staleReview and (
                (month != local.strftime("%Y-%m") and review is None) or age >= rule.days
            ):
                context = {
                    "customer_name": "",
                    "merchant_name": merchant.name,
                    "days": age,
                    "distance_km": "",
                    "month": month,
                    "reason": "Pricing review is due; confirm rates or mark reviewed with no changes.",
                    "trigger": "REVIEW",
                }
                result.append(
                    Candidate("PRICING", f"{month} review", baseline + ":review", context)
                )
        return result

    async def scan_merchant(self, merchant):
        # Merchant lock serializes scheduler passes, visits and review actions.
        await self.session.scalar(
            select(Merchant).where(Merchant.id == merchant.id).with_for_update()
        )
        rules, _, _ = await effective_rules(self.session, merchant.id)
        candidates = (
            await self.candidates(merchant, rules) if any(r.enabled for r in rules.values()) else []
        )
        existing = {
            r.fingerprint: r
            for r in (
                await self.session.scalars(
                    select(Reminder)
                    .where(
                        Reminder.merchant_id == merchant.id,
                        Reminder.kind.in_(["PROXIMITY", "INACTIVE", "PRICING"]),
                        or_(Reminder.kind != "PROXIMITY", Reminder.assigned_user_id.is_(None)),
                        or_(
                            Reminder.status != "RESOLVED",
                            Reminder.fingerprint.in_(
                                [candidate.fingerprint(merchant.id) for candidate in candidates]
                            ),
                        ),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        }
        seen = set()
        staff = {}
        for candidate in candidates:
            self.stats["considered"] += 1
            key = candidate.fingerprint(merchant.id)
            seen.add(key)
            rule = rules[candidate.kind]
            row = existing.get(key)
            if row is None:
                row = Reminder(
                    id=str(uuid4()),
                    fingerprint=key,
                    merchant_id=merchant.id,
                    kind=candidate.kind,
                    customer_id=candidate.customer_id,
                    site_id=candidate.site_id,
                    assigned_user_id=candidate.assigned_user_id,
                    subject=candidate.subject[:180],
                    context=json.dumps(candidate.context),
                    status="OPEN",
                    reminder_count=0,
                    created_at=self.now,
                    updated_at=self.now,
                )
                self.session.add(row)
            elif row.status == "RESOLVED":
                if row.reason != "Condition cleared or policy disabled.":
                    continue
                row.status = "OPEN"
            row.context, row.updated_at, row.reason = json.dumps(candidate.context), self.now, None
            if (
                not in_window(rule, self.now)
                or row.status == "ACKNOWLEDGED"
                or row.reminder_count >= rule.maxCount
            ):
                continue
            if row.next_due_at and utc(row.next_due_at) > self.now:
                continue
            if row.status == "SNOOZED":
                row.status = "OPEN"
            if candidate.kind != "PROXIMITY" and candidate.kind not in staff:
                staff[candidate.kind] = await self.recipients(merchant.id, rule, candidate.kind)
            recipients = [(uid, "user", "MERCHANT") for uid in staff.get(candidate.kind, [])]
            if candidate.kind == "PROXIMITY":
                recipients = [(candidate.customer_id, "customer", "CUSTOMER")]
            elif candidate.kind == "INACTIVE":
                recipients.append((candidate.customer_id, "customer", "CUSTOMER"))
            if not recipients:
                row.reason = "No active authorized recipients."
                self.stats["skipped"] += 1
                continue
            for recipient_id, recipient_kind, channel in recipients:
                template = rule.customerTemplate if channel == "CUSTOMER" else rule.staffTemplate
                # UUID outbox occurrence preserves the existing unique event contract without replacing historical rows.
                NotificationOutboxWriter(self.session).queue(
                    NotificationEvent(
                        event_type=f"automation.{candidate.kind.lower()}.{row.reminder_count + 1}",
                        recipient_kind=recipient_kind,
                        recipient_id=recipient_id,
                        recipient_channel=channel,
                        entity_type="reminder",
                        entity_id=row.id,
                        title=rule.title.format(**candidate.context)[:180],
                        body=template.format(**candidate.context),
                    )
                )
            row.last_sent_at = self.now
            row.reminder_count += 1
            row.next_due_at = self.now + timedelta(hours=rule.intervalHours)
            self.stats["queued"] += len(recipients)
        for key, row in existing.items():
            if key not in seen and row.status != "RESOLVED":
                row.status, row.updated_at, row.reason = (
                    "RESOLVED",
                    self.now,
                    "Condition cleared or policy disabled.",
                )
                self.stats["resolved"] += 1
        await self.session.flush()

    async def run(self):
        # Read-only lookup, then one transaction per merchant: retries cannot duplicate a committed pass.
        ids = (
            await self.session.scalars(
                select(Merchant.id)
                .where(Merchant.status == "ACTIVE", Merchant.approval_status == "APPROVED")
                .order_by(Merchant.id)
            )
        ).all()
        await self.session.rollback()
        for merchant_id in ids:
            # Lock before the first consistent read: MySQL REPEATABLE READ must not
            # establish an old snapshot while another scheduler still owns this merchant.
            merchant = await self.session.scalar(
                select(Merchant)
                .where(
                    Merchant.id == merchant_id,
                    Merchant.status == "ACTIVE",
                    Merchant.approval_status == "APPROVED",
                )
                .with_for_update()
            )
            if merchant is not None:
                await self.scan_merchant(merchant)
            await self.session.commit()
        return self.stats
