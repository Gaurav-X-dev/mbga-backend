from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.pricing.calendar import business_today
from app.shared.authorization.dependencies import (
    require_any_permission,
    require_login_channel,
    require_permission,
)
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

from .export import pricing_export
from .schemas import (
    LABELS,
    BaseRateRequest,
    BrandRequest,
    BrandStatus,
    ConsolidatedExport,
    Filters,
    Pincode,
    PriceRequest,
    customer,
    cylinder,
)
from .service import CompetitorPricingService

VIEW = Depends(require_permission("pricing.view"))
MANAGE = Depends(require_permission("competitor_pricing.manage"))
RECORD = Depends(require_any_permission("pricing.manage", "competitor_pricing.record"))


def service(session: Annotated[AsyncSession, Depends(get_db_session)], actor: ActorDep):
    return CompetitorPricingService(session, actor)


def admin_service(
    session: Annotated[AsyncSession, Depends(get_db_session)], actor: AdminMerchantActorDep
):
    return CompetitorPricingService(session, actor)


def filters(
    pincode: str | None = None,
    cylinderType: str = "19 kg",
    customerType: str = "Retail (Domestic)",
    allPincodes: bool = False,
):
    try:
        return Filters(
            pincode=pincode,
            cylinderType=cylinderType,
            customerType=customerType,
            allPincodes=allPincodes,
        )
    except ValueError as e:
        raise ApiError("VALIDATION_ERROR", 422, "Invalid pricing dimensions.") from e


Filter = Annotated[Filters, Depends(filters)]


def optional_cylinder(value):
    try:
        return cylinder(value) if value else None
    except ValueError as e:
        raise ApiError("VALIDATION_ERROR", 422, str(e)) from e


def build_routers(channel: LoginChannel):
    """Share handlers while selecting the channel-specific authenticated actor adapter."""
    dependencies = [Depends(require_login_channel(channel))]
    if channel is LoginChannel.ADMIN:
        dependencies.append(Depends(require_permission("merchants.view")))
    router = APIRouter(
        prefix="/competitor-pricing", tags=["Competitor Pricing"], dependencies=dependencies
    )
    base_router = APIRouter(
        prefix="/pricing", tags=["Competitor Pricing"], dependencies=dependencies
    )
    Service = Annotated[
        CompetitorPricingService,
        Depends(admin_service if channel is LoginChannel.ADMIN else service),
    ]

    @router.get("/competitors", dependencies=[VIEW])
    async def brands(s: Service, search: Annotated[str | None, Query(max_length=160)] = None):
        return await s.brands(search)

    @router.post("/competitors", status_code=201, dependencies=[MANAGE])
    async def create_brand(payload: BrandRequest, s: Service):
        return await s.create_brand(payload)

    @router.patch("/competitors/{competitor_id}", dependencies=[MANAGE])
    async def brand_status(competitor_id: str, payload: BrandStatus, s: Service):
        return await s.set_status(competitor_id, payload)

    @router.get("/snapshot", dependencies=[VIEW])
    async def snapshot(
        s: Service,
        f: Filter,
        timeframe: Literal["7D", "30D", "3M", "1Y", "CUSTOM"] | None = None,
        startDate: date | None = None,
        endDate: date | None = None,
    ):
        if timeframe or startDate or endDate or f.all_pincodes or f.pincode == "ALL":
            from .filtered import bounds, comparison

            rows = await comparison(s, f, *bounds(timeframe, startDate, endDate))
            result = s.snapshot_view(f, rows)
            result.update(
                aggregation="latest-per-pincode-average"
                if f.all_pincodes or f.pincode == "ALL"
                else "latest-recorded-quote",
                benchmarkBasis="Current STANDARD rate",
            )
            return result
        from .filtered import resolve

        f.pincode = await resolve(s, f)
        return await s.snapshot(f)

    @router.get("/comparison", dependencies=[VIEW])
    async def comparison(
        s: Service,
        f: Filter,
        timeframe: Literal["7D", "30D", "3M", "1Y", "CUSTOM"] | None = None,
        startDate: date | None = None,
        endDate: date | None = None,
    ):
        from .filtered import bounds, resolve
        from .filtered import comparison as filtered_comparison

        if timeframe or startDate or endDate or f.all_pincodes or f.pincode == "ALL":
            return await filtered_comparison(s, f, *bounds(timeframe, startDate, endDate))
        f.pincode = await resolve(s, f)
        return await s.comparison(f)

    @router.post("/prices", dependencies=[RECORD])
    async def record(payload: PriceRequest, s: Service):
        return await s.record(payload)

    @router.get("/audit-logs", dependencies=[VIEW])
    async def audit(
        s: Service,
        cylinderType: str | None = None,
        competitorId: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
        pincode: Pincode | None = None,
        customerType: str | None = None,
        startDate: date | None = None,
        endDate: date | None = None,
    ):
        await s.require_office()
        if (startDate and startDate > business_today()) or (endDate and endDate > business_today()):
            raise ApiError("VALIDATION_ERROR", 422, "Audit dates cannot be in the future.")
        if startDate and endDate and startDate > endDate:
            raise ApiError("VALIDATION_ERROR", 422, "startDate must not exceed endDate.")
        try:
            category = customer(customerType) if customerType else None
        except ValueError as e:
            raise ApiError("VALIDATION_ERROR", 422, str(e)) from e
        return await s.audit(
            optional_cylinder(cylinderType),
            competitorId,
            limit,
            offset,
            pincode,
            category,
            startDate,
            endDate,
        )

    @router.get("/history", dependencies=[VIEW])
    async def history(
        s: Service,
        f: Filter,
        timeframe: Literal["7D", "30D", "3M", "1Y", "CUSTOM"] = "30D",
        startDate: date | None = None,
        endDate: date | None = None,
        dateBasis: Literal["effective", "recorded"] = "effective",
        interval: Literal["auto", "day", "week", "month"] = "auto",
    ):
        from .filtered import bounds, resolve
        from .filtered import history as filtered_history

        if dateBasis == "recorded" or f.all_pincodes or f.pincode == "ALL":
            return await filtered_history(s, f, *bounds(timeframe, startDate, endDate), interval)
        f.pincode = await resolve(s, f)
        return await s.history(f, timeframe, startDate, endDate)

    @router.get("/export", dependencies=[VIEW], response_class=Response)
    async def export(
        s: Service,
        f: Filter,
        format: str = "XLSX",
        cylinderTypes: Annotated[list[str] | None, Query()] = None,
        dataset: Literal["snapshot", "comparison", "history", "audit"] = "comparison",
        timeframe: Literal["7D", "30D", "3M", "1Y", "CUSTOM"] = "30D",
        startDate: date | None = None,
        endDate: date | None = None,
        includeAudit: bool = False,
    ):
        if cylinderTypes is not None or f.all_pincodes or f.pincode in {None, "ALL"}:
            from .filtered import export as consolidated_export

            try:
                request = ConsolidatedExport(
                    format=format,
                    pincode=f.pincode,
                    allPincodes=f.all_pincodes,
                    cylinderTypes=cylinderTypes or list(LABELS),
                    customerType=f.customer_type,
                    timeframe=timeframe,
                    startDate=startDate,
                    endDate=endDate,
                    includeAudit=includeAudit or dataset == "audit",
                )
            except ValueError as exc:
                raise ApiError("VALIDATION_ERROR", 422, str(exc)) from exc
            return await consolidated_export(s, request)
        format = format.upper()
        if format not in {"CSV", "XLSX"}:
            raise ApiError("VALIDATION_ERROR", 422, "format must be CSV or XLSX")
        return await pricing_export(
            s, f, timeframe, startDate, endDate, format, dataset, includeAudit
        )

    @router.post("/export", dependencies=[VIEW], response_class=Response)
    async def consolidated_export(payload: ConsolidatedExport, s: Service):
        from .filtered import export

        return await export(s, payload)

    @base_router.put("/base-rates", dependencies=[Depends(require_permission("pricing.manage"))])
    async def base_rate(payload: BaseRateRequest, s: Service):
        raise ApiError(
            "MBGA_PRICE_EDIT_BLOCKED",
            403,
            "MBGA benchmark prices are system-managed and cannot be modified from the survey module.",
        )

    return router, base_router


router, base_router = build_routers(LoginChannel.MERCHANT)
admin_router, admin_base_router = build_routers(LoginChannel.ADMIN)
