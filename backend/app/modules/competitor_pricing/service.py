"""Market comparisons. Merchant locks serialize quote upserts and monthly rate changes."""

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.modules.authentication.constants import LoginChannel
from app.modules.merchants.models import Merchant
from app.modules.pricing.calendar import business_today
from app.modules.pricing.models import PricingChangeLog, PricingEntry, PricingMonth
from app.modules.pricing.months import PricingMonthProvisioner
from app.shared.exceptions.api_error import ApiError

from .models import Competitor, CompetitorPrice
from .models import CompetitorPriceChangeLog as Log
from .schemas import LABELS

DEPOT_FIELDS = {
    "line1": "depot_line1",
    "line2": "depot_line2",
    "city": "depot_city",
    "state": "depot_state",
    "pincode": "depot_pincode",
    "latitude": "latitude",
    "longitude": "longitude",
}


def audit_boundary(day: date):
    return (
        datetime.combine(day, time.min, tzinfo=ZoneInfo("Asia/Kolkata"))
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


def history_bounds(timeframe, start_date=None, end_date=None):
    today = business_today()
    if timeframe == "CUSTOM":
        if start_date is None or end_date is None:
            raise ApiError("VALIDATION_ERROR", 422, "CUSTOM requires startDate and endDate.")
        if start_date > end_date or end_date > today:
            raise ApiError("VALIDATION_ERROR", 422, "Use startDate <= endDate <= today.")
        if (end_date - start_date).days > 365:
            raise ApiError("VALIDATION_ERROR", 422, "Custom ranges cannot exceed 366 days.")
        return start_date, end_date
    if start_date is not None or end_date is not None:
        raise ApiError("VALIDATION_ERROR", 422, "Dates are supported only with timeframe=CUSTOM.")
    return today - timedelta(days={"7D": 6, "30D": 29, "3M": 89, "1Y": 364}[timeframe]), today


def rounded(value, places=0):
    return float(Decimal(value).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def delta(old, new):
    diff = new - old
    return {
        "oldPrice": float(old),
        "newPrice": float(new),
        "changeAmount": float(abs(diff)),
        "changeType": "INCREASED" if diff > 0 else "DECREASED" if diff < 0 else "SAME",
    }


class CompetitorPricingService:
    def __init__(self, session, actor):
        self.session, self.actor = session, actor
        self.merchant_id = actor.require_merchant_id()

    async def lock(self):
        await self.session.scalar(
            select(Merchant).where(Merchant.id == self.merchant_id).with_for_update()
        )

    async def brand(self, brand_id):
        brand = await self.session.scalar(
            select(Competitor)
            .where(Competitor.id == brand_id, Competitor.merchant_id == self.merchant_id)
            .with_for_update()
        )
        if brand is None:
            raise ApiError("NOT_FOUND", 404)
        return brand

    @staticmethod
    def brand_view(b):
        return {
            "id": b.id,
            "name": b.name,
            "code": b.code,
            "color": b.color,
            "iconName": b.icon_name,
            "status": b.status,
            "notes": b.notes,
            "createdAt": b.created_at,
            "updatedAt": b.updated_at,
            "lastUpdated": b.updated_at,
            "depotAddress": {
                "line1": b.depot_line1,
                "line2": b.depot_line2,
                "city": b.depot_city,
                "state": b.depot_state,
                "pincode": b.depot_pincode,
                "latitude": float(b.latitude) if b.latitude is not None else None,
                "longitude": float(b.longitude) if b.longitude is not None else None,
            }
            if any(getattr(b, field) is not None for field in DEPOT_FIELDS.values())
            else None,
        }

    async def brands(self, search=None):
        stmt = select(Competitor).where(Competitor.merchant_id == self.merchant_id)
        if search:
            stmt = stmt.where(
                or_(
                    Competitor.name.contains(search, autoescape=True),
                    Competitor.code.contains(search.upper(), autoescape=True),
                )
            )
        return [
            self.brand_view(b) for b in await self.session.scalars(stmt.order_by(Competitor.name))
        ]

    async def create_brand(self, payload):
        await self.lock()
        code = re.sub(r"[^A-Z0-9]", "", payload.name.upper())[:10]
        if not code:
            raise ApiError("VALIDATION_ERROR", 422, "Name must contain a letter or digit.")
        if await self.session.scalar(
            select(Competitor.id).where(
                Competitor.merchant_id == self.merchant_id, Competitor.code == code
            )
        ):
            raise ApiError("CONFLICT", 409, "A competitor with this code already exists.")
        now = datetime.now(UTC)
        brand = Competitor(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            name=payload.name,
            code=code,
            color=payload.color,
            icon_name=payload.icon_name,
            notes=payload.notes,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self.apply_depot(brand, payload.depot_address)
        self.session.add(brand)
        await self.session.commit()
        return self.brand_view(brand)

    async def set_status(self, brand_id, payload):
        await self.lock()
        brand = await self.brand(brand_id)
        fields = getattr(payload, "model_fields_set", {"status"})
        if "status" in fields:
            brand.status = payload.status
        if "notes" in fields:
            brand.notes = payload.notes
        if "depot_address" in fields:
            self.apply_depot(brand, payload.depot_address)
        brand.updated_at = datetime.now(UTC)
        await self.session.commit()
        return self.brand_view(brand)

    @staticmethod
    def apply_depot(brand, address):
        for key, column in DEPOT_FIELDS.items():
            value = getattr(address, key) if address else None
            if key in {"latitude", "longitude"} and value is not None:
                value = value.quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)
            setattr(brand, column, value)

    async def require_office(self):
        # Admin routes already require an admin session, merchants.view, pricing.view,
        # and a validated explicit merchantId; retain the admin's audit identity.
        if self.actor.login_channel is LoginChannel.ADMIN:
            return

        from app.modules.roles.models import Role
        from app.modules.users.role_models import UserRole

        if (self.actor.staff_type or "").lower() in {
            "primary_manager",
            "manager",
            "store_manager",
            "store manager",
            "owner",
            "admin",
            "merchant admin",
        }:
            return
        role = await self.session.scalar(
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == self.actor.user_id,
                Role.is_active.is_(True),
                Role.code.in_(["owner", "admin", "manager", "store_manager"]),
            )
            .limit(1)
        )
        if role is None:
            raise ApiError("FORBIDDEN", 403, "Audit access is restricted to office staff.")

    def observation(
        self, competitor_id, name, cylinder, old, new, effective, notes, customer=None, pincode=None
    ):
        row = Log(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            competitor_id=competitor_id,
            competitor_name=name,
            cylinder_type=cylinder,
            customer_type=customer,
            location_pincode=pincode,
            old_price=old,
            new_price=new,
            effective_date=effective,
            changed_by_user_id=self.actor.user_id,
            changed_by_user_name=self.actor.display_name,
            changed_by_user_role=self.actor.role_label,
            notes=notes,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        return row

    @staticmethod
    def quote_view(q, name):
        return dict(
            id=q.id,
            competitorId=q.competitor_id,
            competitorName=name,
            cylinderType=LABELS[q.cylinder_type],
            customerType=q.customer_type,
            locationPincode=q.location_pincode,
            price=float(q.price),
            **delta(q.old_price, q.price),
            effectiveDate=q.effective_date,
            notes=q.notes,
            updatedBy=q.updated_by,
            updatedByRole=q.updated_by_role,
            updatedAt=q.updated_at,
        )

    async def record(self, p):
        if p.competitor_id.lower() in {"mbga_self", "mbga"}:
            raise ApiError(
                "MBGA_PRICE_EDIT_BLOCKED",
                403,
                "MBGA benchmark prices are system-managed and cannot be modified from the survey module.",
            )
        # Future dates would make a pending quote overwrite the current active quote.
        if p.effective_date > business_today():
            raise ApiError("VALIDATION_ERROR", 422, "Future-effective quotes are not supported.")
        await self.lock()
        brand = await self.brand(p.competitor_id)
        if brand.code.upper() == "MBGA":
            raise ApiError(
                "MBGA_PRICE_EDIT_BLOCKED", 403, "MBGA benchmark prices are system-managed."
            )
        if brand.status != "ACTIVE":
            raise ApiError("CONFLICT", 409, "Competitor is inactive.")
        q = await self.session.scalar(
            select(CompetitorPrice)
            .where(
                CompetitorPrice.merchant_id == self.merchant_id,
                CompetitorPrice.competitor_id == brand.id,
                CompetitorPrice.cylinder_type == p.cylinder_type,
                CompetitorPrice.customer_type == p.customer_type,
                CompetitorPrice.location_pincode == p.location_pincode,
            )
            .with_for_update()
        )
        old = q.price if q else p.price
        if q and p.effective_date < q.effective_date:
            raise ApiError("CONFLICT", 409, "Effective date predates the current quote.")
        if q is None:
            q = CompetitorPrice(
                id=str(uuid4()),
                merchant_id=self.merchant_id,
                competitor_id=brand.id,
                cylinder_type=p.cylinder_type,
                customer_type=p.customer_type,
                location_pincode=p.location_pincode,
            )
            self.session.add(q)
        q.old_price, q.price, q.effective_date = old, p.price, p.effective_date
        q.notes, q.updated_by, q.updated_by_role = (
            p.notes,
            self.actor.display_name,
            self.actor.role_label,
        )
        q.updated_at = brand.updated_at = datetime.now(UTC)
        # Every survey is retained; unchanged values stay out of price-change audits.
        self.observation(
            brand.id,
            brand.name,
            p.cylinder_type,
            old,
            p.price,
            p.effective_date,
            p.notes,
            p.customer_type,
            p.location_pincode,
        )
        await self.session.commit()
        return {
            "success": True,
            "message": "Competitor price saved",
            "record": self.quote_view(q, brand.name),
        }

    async def benchmark(self, cylinder, *, read_only=False):
        if read_only:
            current = await self.session.scalar(
                select(PricingMonth)
                .where(
                    PricingMonth.merchant_id == self.merchant_id,
                    PricingMonth.status == "ACTIVE",
                    PricingMonth.effective_from <= business_today(),
                    PricingMonth.effective_to >= business_today(),
                )
                .order_by(PricingMonth.effective_from.desc())
                .limit(1)
            )
            if current is not None:
                entry = await self.session.scalar(
                    select(PricingEntry).where(
                        PricingEntry.pricing_month_id == current.id,
                        PricingEntry.cylinder_type == cylinder,
                        PricingEntry.tier == "STANDARD",
                    )
                )
                if entry is not None:
                    return current, entry
        month = await PricingMonthProvisioner(
            self.session, self.merchant_id, self.actor.merchant_code
        ).ensure_current()
        entry = await self.session.scalar(
            select(PricingEntry)
            .where(
                PricingEntry.pricing_month_id == month.id,
                PricingEntry.cylinder_type == cylinder,
                PricingEntry.tier == "STANDARD",
            )
            .with_for_update()
        )
        if entry is None:
            raise ApiError("NOT_FOUND", 404, "No STANDARD rate exists for this cylinder.")
        return month, entry

    async def comparison(self, f):
        month, entry = await self.benchmark(f.cylinder_type, read_only=True)
        price = entry.bpcl_base_rate + entry.tier_markup
        rows = [
            {
                "competitorId": "mbga_self",
                "name": "MBGA (Your Price)",
                "price": float(price),
                "difference": 0,
                "differencePercentage": 0,
                "isMbga": True,
                "color": "#2563EB",
                "iconName": "flame",
                "updatedAt": month.updated_at,
                "updatedBy": month.updated_by,
                "updatedByRole": None,
            }
        ]
        result = await self.session.execute(
            select(CompetitorPrice, Competitor)
            .join(Competitor, Competitor.id == CompetitorPrice.competitor_id)
            .where(
                CompetitorPrice.merchant_id == self.merchant_id,
                Competitor.merchant_id == self.merchant_id,
                Competitor.status == "ACTIVE",
                CompetitorPrice.cylinder_type == f.cylinder_type,
                CompetitorPrice.customer_type == f.customer_type,
                CompetitorPrice.location_pincode == f.pincode,
                CompetitorPrice.effective_date <= business_today(),
            )
            .order_by(CompetitorPrice.price, Competitor.name)
        )
        for q, b in result:
            rows.append(
                self.quote_view(q, b.name)
                | {
                    "competitorId": b.id,
                    "name": b.name,
                    "code": b.code,
                    "difference": float(q.price - price),
                    "differencePercentage": rounded((q.price - price) / price * 100, 1)
                    if price
                    else 0,
                    "isMbga": False,
                    "color": b.color,
                    "iconName": b.icon_name,
                }
            )
        await self.session.commit()
        return rows

    async def snapshot(self, f):
        rows = await self.comparison(f)
        return self.snapshot_view(f, rows)

    @staticmethod
    def snapshot_view(f, rows):
        price = Decimal(str(rows[0]["price"]))
        avg = (
            Decimal(str(rounded(sum(Decimal(str(r["price"])) for r in rows[1:]) / (len(rows) - 1))))
            if len(rows) > 1
            else price + 75
        )
        diff = abs(avg - price)
        return {
            "cylinderType": LABELS[f.cylinder_type],
            "cylinderLabel": LABELS[f.cylinder_type],
            "mbgaPrice": float(price),
            "avgCompetitorPrice": float(avg),
            "difference": float(diff),
            "differencePercentage": rounded(diff / avg * 100, 1) if avg else 0,
            "isLower": price < avg,
            "hasCompetitorQuotes": len(rows) > 1,
            "competitorQuoteCount": len(rows) - 1,
        }

    async def base_rate(self, p):
        await self.lock()
        month, entry = await self.benchmark(p.cylinder_type)
        if month.status != "ACTIVE":
            raise ApiError("CONFLICT", 409, "Pricing month is not active.")
        old = entry.bpcl_base_rate + entry.tier_markup
        # Reject an impossible total rather than silently saving a different selling price.
        if p.price < entry.tier_markup:
            raise ApiError("VALIDATION_ERROR", 422, "Selling price must cover the tier markup.")
        now = datetime.now(UTC)
        if old != p.price:
            self.session.add(
                PricingChangeLog(
                    merchant_id=self.merchant_id,
                    pricing_month_id=month.id,
                    cylinder_type=entry.cylinder_type,
                    tier=entry.tier,
                    old_bpcl_base_rate=entry.bpcl_base_rate,
                    old_tier_markup=entry.tier_markup,
                    old_customer_price=old,
                    new_bpcl_base_rate=p.price - entry.tier_markup,
                    new_tier_markup=entry.tier_markup,
                    new_customer_price=p.price,
                    effective_from=business_today(),
                    reason=p.notes,
                    changed_by_user_id=self.actor.user_id,
                    changed_by_name=self.actor.display_name,
                    changed_by_role=self.actor.role_label,
                    changed_at=now,
                )
            )
            self.observation(
                "mbga_self",
                "MBGA (Your Price)",
                p.cylinder_type,
                old,
                p.price,
                business_today(),
                p.notes,
            )
            entry.bpcl_base_rate = p.price - entry.tier_markup
            month.updated_by, month.updated_at = self.actor.display_name, now
        await self.session.commit()
        return {
            "success": True,
            "cylinderType": LABELS[p.cylinder_type],
            "mbgaPrice": float(p.price),
            "updatedAt": now,
        }

    async def audit(
        self,
        cylinder=None,
        competitor=None,
        limit=20,
        offset=0,
        pincode=None,
        customer_type=None,
        start_date=None,
        end_date=None,
    ):
        stmt = select(Log).where(
            Log.merchant_id == self.merchant_id, Log.old_price != Log.new_price
        )
        if cylinder:
            stmt = stmt.where(Log.cylinder_type == cylinder)
        if competitor:
            stmt = stmt.where(Log.competitor_id == competitor)
        if pincode:
            stmt = stmt.where(
                or_(Log.competitor_id == "mbga_self", Log.location_pincode == pincode)
            )
        if customer_type:
            stmt = stmt.where(
                or_(Log.competitor_id == "mbga_self", Log.customer_type == customer_type)
            )
        if start_date:
            stmt = stmt.where(Log.created_at >= audit_boundary(start_date))
        if end_date:
            stmt = stmt.where(Log.created_at < audit_boundary(end_date + timedelta(days=1)))
        rows = await self.session.scalars(
            stmt.order_by(Log.created_at.desc(), Log.id).limit(limit).offset(offset)
        )
        brands = {
            b.id: b
            for b in await self.session.scalars(
                select(Competitor).where(Competitor.merchant_id == self.merchant_id)
            )
        }
        result = []
        for r in rows:
            d = r.new_price - r.old_price
            b = brands.get(r.competitor_id)
            result.append(
                {
                    "id": r.id,
                    "competitorId": r.competitor_id,
                    "competitorName": r.competitor_name,
                    "cylinderType": LABELS[r.cylinder_type],
                    "customerType": r.customer_type,
                    "locationPincode": r.location_pincode,
                    "oldPrice": float(r.old_price),
                    "newPrice": float(r.new_price),
                    "difference": float(d),
                    "isIncrease": d > 0,
                    "changeText": f"Price {'increased' if d > 0 else 'decreased'} from ₹{r.old_price:,.2f} to ₹{r.new_price:,.2f}",
                    "changedByUserId": r.changed_by_user_id,
                    "changedBy": r.changed_by_user_name,
                    "changedByRole": r.changed_by_user_role,
                    "timestamp": r.created_at.replace(tzinfo=UTC),
                    "effectiveDate": r.effective_date,
                    "notes": r.notes,
                    "color": b.color if b else "#2563EB",
                    "iconName": b.icon_name if b else "flame",
                }
            )
        return result

    async def history(self, f, timeframe, start_date=None, end_date=None, *, benchmark_only=False):
        start, today = history_bounds(timeframe, start_date, end_date)
        # Read observations before the window too, to carry the last known rate forward.
        logs = list(
            await self.session.scalars(
                select(Log)
                .where(
                    Log.merchant_id == self.merchant_id,
                    Log.cylinder_type == f.cylinder_type,
                    Log.effective_date <= today,
                    Log.competitor_id == "mbga_self" if benchmark_only else True,
                    (
                        (Log.competitor_id == "mbga_self")
                        | (
                            (Log.customer_type == f.customer_type)
                            & (Log.location_pincode == f.pincode)
                        )
                    ),
                )
                .order_by(Log.effective_date, Log.created_at, Log.id)
            )
        )
        brands = list(
            await self.session.scalars(
                select(Competitor).where(Competitor.merchant_id == self.merchant_id)
            )
        )
        aliases = {
            "BHARAT": "bharatGas",
            "BHARATGAS": "bharatGas",
            "INDANE": "indane",
            "HP": "hpGas",
            "HPGAS": "hpGas",
        }
        keys = {b.id: aliases.get(b.code, b.id) for b in brands} | {"mbga_self": "mbga"}
        # Include regular pricing changes, even when edited outside this module.
        changes = list(
            await self.session.scalars(
                select(PricingChangeLog)
                .where(
                    PricingChangeLog.merchant_id == self.merchant_id,
                    PricingChangeLog.cylinder_type == f.cylinder_type,
                    PricingChangeLog.tier == "STANDARD",
                    PricingChangeLog.effective_from <= today,
                )
                .order_by(PricingChangeLog.effective_from, PricingChangeLog.changed_at)
            )
        )
        events = [
            (r.effective_date, r.created_at.replace(tzinfo=UTC), r.competitor_id, r.new_price)
            for r in logs
        ]
        for r in changes:
            events.append(
                (
                    r.effective_from,
                    r.changed_at.replace(tzinfo=UTC),
                    "mbga_self",
                    r.new_customer_price,
                )
            )
        # A month's saved entry supplies a baseline even if nobody edited it. When
        # changes exist, the earliest log's old price recovers the opening rate.
        month_entries = await self.session.execute(
            select(PricingMonth, PricingEntry)
            .join(PricingEntry, PricingEntry.pricing_month_id == PricingMonth.id)
            .where(
                PricingMonth.merchant_id == self.merchant_id,
                PricingMonth.effective_from <= today,
                PricingEntry.cylinder_type == f.cylinder_type,
                PricingEntry.tier == "STANDARD",
            )
        )
        for month, entry in month_entries:
            first = next((r for r in changes if r.pricing_month_id == month.id), None)
            opening = (
                first.old_customer_price
                if first and first.old_customer_price is not None
                else entry.bpcl_base_rate + entry.tier_markup
            )
            events.append(
                (month.effective_from, datetime.min.replace(tzinfo=UTC), "mbga_self", opening)
            )
        events.sort(key=lambda e: (e[0], e[1]))
        values, result, index = {}, [], 0
        day = start
        while day <= today:
            while index < len(events) and events[index][0] <= day:
                _, _, cid, value = events[index]
                values[keys.get(cid, cid)] = float(value)
                index += 1
            result.append({"date": day.isoformat(), **values})
            day += timedelta(days=1)
        return result
