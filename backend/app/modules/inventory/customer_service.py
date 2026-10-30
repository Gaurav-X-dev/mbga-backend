"""Customer-owned views of completed handovers; never writes or changes a ledger."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_catalogue.models import (
    CustomerTypeCylinder,
    CustomerTypeDefinition,
    CylinderTypeDefinition,
)
from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.constants import DeliveryStatus
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.inventory.customer_schemas import (
    CylinderOption,
    FiltersResponse,
    HoldingItem,
    InventoryResponse,
    Movement,
    MovementOption,
    MovementsResponse,
    MovementSummary,
    Pagination,
    Period,
)
from app.shared.business.actor import BusinessActor
from app.shared.date_time.business_calendar import business_day_window
from app.shared.exceptions.api_error import ApiError


def invalid(field, message):
    return ApiError(
        "VALIDATION_ERROR", 422, fields=[{"field": field, "code": "invalid", "message": message}]
    )


def size_label(definition, code):
    # Never return marketing/customer-category wording as a customer inventory label.
    if definition is not None:
        weight = format(Decimal(definition.weight_kg), "f")
        if "." in weight:
            weight = weight.rstrip("0").rstrip(".")
        return f"{weight} KG"
    # Legacy identifiers have no catalogue definition; retain the history without displaying codes.
    match = re.search(r"(\d+(?:[._]\d+)?)\s*KG", code, re.IGNORECASE)
    return f"{match.group(1).replace('_', '.')} KG" if match else "Cylinder"


class CustomerInventoryService:
    def __init__(self, session: AsyncSession, actor: BusinessActor):
        self.session, self.actor = session, actor

    async def profile(self):
        if not self.actor.is_customer:
            raise ApiError("CHANNEL_NOT_ALLOWED", 403)
        if not self.actor.customer_id:
            raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", 404)
        profile = await self.session.get(CustomerProfile, self.actor.customer_id)
        if profile is None:
            raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", 404)
        if self.actor.merchant_id and profile.merchant_id != self.actor.merchant_id:
            raise ApiError("CHANNEL_NOT_ALLOWED", 403)
        return profile

    def scope(self, profile):
        return (
            DeliverySlip.customer_id == profile.id,
            DeliverySlip.merchant_id == profile.merchant_id,
            DeliverySlip.status == DeliveryStatus.DELIVERED.value,
        )

    async def catalogue(self, profile):
        # Eligibility controls new choices. Historic types remain visible only when this
        # customer's completed slips actually contain a handover of that type.
        eligible_rows = (
            (
                await self.session.execute(
                    select(CylinderTypeDefinition)
                    .join(
                        CustomerTypeCylinder,
                        CustomerTypeCylinder.cylinder_type_code == CylinderTypeDefinition.code,
                    )
                    .join(
                        CustomerTypeDefinition,
                        CustomerTypeDefinition.code == CustomerTypeCylinder.customer_type_code,
                    )
                    .where(
                        CustomerTypeCylinder.customer_type_code == profile.customer_type,
                        CustomerTypeCylinder.is_active.is_(True),
                        CustomerTypeDefinition.is_active.is_(True),
                        CylinderTypeDefinition.is_active.is_(True),
                    )
                    .order_by(
                        CustomerTypeCylinder.sort_order,
                        CylinderTypeDefinition.sort_order,
                        CylinderTypeDefinition.code,
                    )
                )
            )
            .scalars()
            .all()
        )
        eligible = {row.code for row in eligible_rows}
        delivered = func.coalesce(DeliverySlipItem.delivered_quantity, DeliverySlipItem.quantity)
        returned = func.coalesce(DeliverySlipItem.empties_collected, 0)
        totals = (
            await self.session.execute(
                select(DeliverySlipItem.cylinder_type, func.sum(delivered), func.sum(returned))
                .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
                .where(*self.scope(profile), or_(delivered > 0, returned > 0))
                .group_by(DeliverySlipItem.cylinder_type)
            )
        ).all()
        counts = {code: (int(given), int(back)) for code, given, back in totals}
        historical = sorted(set(counts) - eligible)
        definitions = {row.code: row for row in eligible_rows}
        if historical:
            for row in (
                await self.session.scalars(
                    select(CylinderTypeDefinition).where(
                        CylinderTypeDefinition.code.in_(historical)
                    )
                )
            ).all():
                definitions[row.code] = row
        codes = [row.code for row in eligible_rows] + historical
        options = {}
        for code in codes:
            definition = definitions.get(code)
            variant = definition.variant if definition is not None else None
            options[code] = CylinderOption(
                code=code,
                label=size_label(definition, code),
                variant=variant,
                is_eligible_for_ordering=code in eligible,
                historical_only=code not in eligible,
            )
        return options, counts

    @staticmethod
    def check_type(code, options):
        if code is not None and code not in options:
            raise invalid(
                "cylinderType", "Select an eligible cylinder type or one in your own history."
            )

    async def snapshot(self, cylinder_type=None):
        profile = await self.profile()
        options, counts = await self.catalogue(profile)
        self.check_type(cylinder_type, options)
        items = []
        for code, option in options.items():
            if cylinder_type and code != cylinder_type:
                continue
            given, back = counts.get(code, (0, 0))
            items.append(
                HoldingItem(
                    cylinder_type=code,
                    cylinder_label=option.label,
                    variant=option.variant,
                    is_eligible_for_ordering=option.is_eligible_for_ordering,
                    historical_only=option.historical_only,
                    total_delivered=given,
                    total_returned=back,
                    current_holding=max(0, given - back),
                )
            )
        return InventoryResponse(
            as_of=datetime.now(UTC),
            total_holding=sum(x.current_holding for x in items),
            items=items,
        )

    async def filters(self):
        profile = await self.profile()
        options, _ = await self.catalogue(profile)
        return FiltersResponse(
            cylinder_types=list(options.values()),
            movement_types=[
                MovementOption(code="DELIVERY", label="Deliveries"),
                MovementOption(code="RETURN", label="Returns"),
            ],
            variants=sorted({x.variant for x in options.values() if x.variant}),
        )

    async def movements(
        self,
        *,
        date_from=None,
        date_to=None,
        cylinder_type=None,
        movement_type=None,
        variant=None,
        order_id=None,
        delivery_slip_id=None,
        search=None,
        sort_order="desc",
        page=1,
        page_size=20,
    ):
        if date_from and date_to and date_from > date_to:
            raise invalid("dateTo", "End date must be on or after start date.")
        # The exclusive upper day must be representable for the business-day window.
        if date_to in (date.min, date.max) or date_from in (date.min, date.max):
            raise invalid("dateTo", "Date is outside the supported range.")
        profile = await self.profile()
        options, _ = await self.catalogue(profile)
        self.check_type(cylinder_type, options)
        if variant is not None and variant not in {x.variant for x in options.values()}:
            raise invalid("variant", "Select a variant from the inventory filters response.")
        timestamp = func.coalesce(DeliverySlip.delivered_at, DeliverySlip.updated_at)
        conditions = list(self.scope(profile))
        if date_from:
            conditions.append(timestamp >= business_day_window(date_from)[0])
        if date_to:
            conditions.append(timestamp < business_day_window(date_to)[1])
        if cylinder_type:
            conditions.append(DeliverySlipItem.cylinder_type == cylinder_type)
        if variant:
            conditions.append(
                DeliverySlipItem.cylinder_type.in_(
                    [c for c, o in options.items() if o.variant == variant]
                )
            )
        if order_id:
            conditions.append(DeliverySlip.order_id == order_id)
        if delivery_slip_id:
            conditions.append(DeliverySlip.id == delivery_slip_id)
        if search and search.strip():
            term = search.strip()
            conditions.append(
                or_(
                    DeliverySlip.order_number.contains(term, autoescape=True),
                    DeliverySlip.slip_number.contains(term, autoescape=True),
                )
            )

        def branch(kind, quantity):
            return (
                select(
                    DeliverySlipItem.id.label("line_id"),
                    DeliverySlipItem.cylinder_type.label("cylinder_type"),
                    literal(kind).label("movement_type"),
                    quantity.label("quantity"),
                    timestamp.label("occurred_at"),
                    case(
                        (DeliverySlip.delivered_at.is_not(None), "DELIVERED_AT"),
                        else_="UPDATED_AT_FALLBACK",
                    ).label("timestamp_source"),
                    DeliverySlip.id.label("delivery_slip_id"),
                    DeliverySlip.slip_number.label("delivery_slip_number"),
                    DeliverySlip.order_id.label("order_id"),
                    DeliverySlip.order_number.label("order_number"),
                )
                .select_from(DeliverySlipItem)
                .join(DeliverySlip, DeliverySlip.id == DeliverySlipItem.slip_id)
                .where(*conditions, quantity > 0)
            )

        branches = []
        if movement_type in (None, "DELIVERY"):
            branches.append(
                branch(
                    "DELIVERY",
                    func.coalesce(DeliverySlipItem.delivered_quantity, DeliverySlipItem.quantity),
                )
            )
        if movement_type in (None, "RETURN"):
            branches.append(branch("RETURN", func.coalesce(DeliverySlipItem.empties_collected, 0)))
        events = (union_all(*branches) if len(branches) > 1 else branches[0]).subquery()
        total, given, back = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case((events.c.movement_type == "DELIVERY", events.c.quantity), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case((events.c.movement_type == "RETURN", events.c.quantity), else_=0)
                        ),
                        0,
                    ),
                ).select_from(events)
            )
        ).one()
        columns = [
            events.c.occurred_at,
            events.c.delivery_slip_id,
            events.c.line_id,
            events.c.movement_type,
        ]
        ordering = [x.desc() if sort_order == "desc" else x.asc() for x in columns]
        rows = (
            (
                await self.session.execute(
                    select(events)
                    .order_by(*ordering)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .mappings()
            .all()
        )
        items = []
        for row in rows:
            code, kind = row["cylinder_type"], row["movement_type"]
            option = options[code]
            items.append(
                Movement(
                    id=f"{row['delivery_slip_id']}:{code}:{kind}",
                    movement_type=kind,
                    occurred_at=row["occurred_at"],
                    cylinder_type=code,
                    cylinder_label=option.label,
                    variant=option.variant,
                    quantity=row["quantity"],
                    holding_delta=row["quantity"] if kind == "DELIVERY" else -row["quantity"],
                    order_id=row["order_id"],
                    order_number=row["order_number"],
                    delivery_slip_id=row["delivery_slip_id"],
                    delivery_slip_number=row["delivery_slip_number"],
                    timestamp_source=row["timestamp_source"],
                )
            )
        return MovementsResponse(
            period=Period(date_from=date_from, date_to=date_to),
            summary=MovementSummary(
                delivered_quantity=given, returned_quantity=back, net_movement=given - back
            ),
            items=items,
            pagination=Pagination(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=(total + page_size - 1) // page_size,
                has_next=page * page_size < total,
            ),
        )
