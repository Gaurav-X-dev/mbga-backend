"""Recorded-date market views and bounded multi-market downloads."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.responses import Response
from sqlalchemy import func, select, text

from app.modules.merchants.models import Merchant
from app.modules.reports.export import _csv, xlsx_workbook
from app.shared.exceptions.api_error import ApiError

from .models import Competitor
from .models import CompetitorPriceChangeLog as Log
from .schemas import LABELS, Filters
from .service import audit_boundary, history_bounds

MAX_ROWS = 10000


def bounds(timeframe=None, start=None, end=None):
    return history_bounds(timeframe or ("CUSTOM" if start or end else "30D"), start, end)


async def resolve(service, filters, *, export=False):
    if filters.all_pincodes or filters.pincode == "ALL" or (export and filters.pincode is None):
        return None
    if filters.pincode:
        return filters.pincode
    merchant = await service.session.scalar(
        select(Merchant).where(Merchant.id == service.merchant_id)
    )
    code = merchant.postal_code if merchant else None
    if not code or len(code) != 6 or not code.isdigit() or code[0] == "0":
        raise ApiError(
            "PINCODE_REQUIRED",
            422,
            "Select a pincode; no valid merchant hub pincode is configured.",
        )
    return code


def observation_query(service, pins, cylinders, category, start, end, active=True):
    query = (
        select(Log, Competitor)
        .join(Competitor, Competitor.id == Log.competitor_id)
        .where(
            Log.merchant_id == service.merchant_id,
            Competitor.merchant_id == service.merchant_id,
            Log.customer_type == category,
            Log.cylinder_type.in_(cylinders),
            Log.created_at >= audit_boundary(start),
            Log.created_at < audit_boundary(end + timedelta(days=1)),
        )
    )
    if pins:
        query = query.where(Log.location_pincode == pins)
    if active:
        query = query.where(Competitor.status == "ACTIVE")
    return query


async def observations(service, pin, cylinders, category, start, end, active=True):
    result = list(
        await service.session.execute(
            observation_query(service, pin, cylinders, category, start, end, active)
            .order_by(Log.created_at, Log.id)
            .limit(MAX_ROWS + 1)
        )
    )
    if len(result) > MAX_ROWS:
        raise ApiError(
            "COMPETITOR_EXPORT_LIMIT",
            422,
            "More than 10,000 observations match. Narrow the date range or market filters.",
        )
    return result


async def comparison(service, filters, start, end):
    pin = await resolve(service, filters)
    # Rank in SQL: one latest observation per competitor and market, bounded result size.
    base = observation_query(
        service, pin, [filters.cylinder_type], filters.customer_type, start, end
    )
    ranked = base.with_only_columns(
        Log.id.label("id"),
        func.row_number()
        .over(
            partition_by=(Log.competitor_id, Log.location_pincode),
            order_by=(Log.created_at.desc(), Log.id.desc()),
        )
        .label("rn"),
    ).subquery()
    result = list(
        await service.session.execute(
            select(Log, Competitor)
            .join(Competitor, Competitor.id == Log.competitor_id)
            .join(ranked, ranked.c.id == Log.id)
            .where(ranked.c.rn == 1)
            .limit(MAX_ROWS + 1)
        )
    )
    if len(result) > MAX_ROWS:
        raise ApiError("COMPETITOR_EXPORT_LIMIT", 422, "Too many market quotes. Select a pincode.")
    month, entry = await service.benchmark(filters.cylinder_type, read_only=True)
    benchmark = entry.bpcl_base_rate + entry.tier_markup
    rows = [
        {
            "competitorId": "mbga_self",
            "name": "MBGA (Your Price)",
            "code": "MBGA",
            "price": float(benchmark),
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
    groups = defaultdict(list)
    for log, brand in result:
        groups[brand.id].append((log, brand))
    for cid, values in groups.items():
        log, brand = max(values, key=lambda pair: (pair[0].created_at, pair[0].id))
        price = sum((pair[0].new_price for pair in values), Decimal(0)) / len(values)
        rows.append(
            {
                "competitorId": cid,
                "name": brand.name,
                "code": brand.code,
                "price": round(float(price), 2),
                "difference": round(float(price - benchmark), 2),
                "differencePercentage": round(float((price - benchmark) / benchmark * 100), 2)
                if benchmark
                else 0,
                "isMbga": False,
                "color": brand.color,
                "iconName": brand.icon_name,
                "updatedAt": log.created_at,
                "updatedBy": log.changed_by_user_name,
                "updatedByRole": log.changed_by_user_role,
                "effectiveDate": log.effective_date,
                "notes": log.notes,
                "quoteMarketCount": len(values),
                "aggregation": "latest-per-pincode-average"
                if pin is None
                else "latest-recorded-quote",
            }
        )
    return rows[:1] + sorted(rows[1:], key=lambda row: (row["price"], row["name"]))


async def history(service, filters, start, end, interval="auto"):
    pin = await resolve(service, filters)
    # SQL daily averages, no raw survey dump or pre-window carry-forward.
    bind = getattr(service.session, "bind", None)
    dialect = bind.dialect.name if bind else service.session.sync.get_bind().dialect.name
    local_day = (
        func.date(func.datetime(Log.created_at, "+330 minutes"))
        if dialect == "sqlite"
        else func.date(func.date_add(Log.created_at, text("INTERVAL 330 MINUTE")))
    )
    base = observation_query(
        service, pin, [filters.cylinder_type], filters.customer_type, start, end
    )
    query = base.with_only_columns(
        local_day.label("day"), Log.competitor_id, Competitor.code, func.avg(Log.new_price)
    ).group_by(local_day, Log.competitor_id, Competitor.code)
    grouped = defaultdict(dict)
    aliases = {
        "BHARAT": "bharatGas",
        "BHARATGAS": "bharatGas",
        "INDANE": "indane",
        "HP": "hpGas",
        "HPGAS": "hpGas",
    }
    for day, cid, code, price in await service.session.execute(query):
        grouped[str(day)][aliases.get(code, cid)] = float(price)
    if interval == "auto":
        interval = "week" if (end - start).days >= 60 else "day"
    buckets = defaultdict(lambda: defaultdict(list))
    for day, values in grouped.items():
        parsed = date.fromisoformat(day)
        bucket = (
            start + timedelta(days=((parsed - start).days // 7) * 7)
            if interval == "week"
            else parsed.replace(day=1)
            if interval == "month"
            else parsed
        )
        for cid, price in values.items():
            buckets[bucket.isoformat()][cid].append(price)
    baseline = {
        row["date"]: row.get("mbga")
        for row in await service.history(filters, "CUSTOM", start, end, benchmark_only=True)
    }
    return [
        dict(
            date=day,
            **({"mbga": baseline[day]} if baseline.get(day) is not None else {}),
            **{cid: round(sum(prices) / len(prices), 2) for cid, prices in values.items()},
        )
        for day, values in sorted(buckets.items())
    ]


async def export(service, request):
    start, end = bounds(request.timeframe, request.start_date, request.end_date)
    f = Filters(
        pincode=request.pincode,
        allPincodes=request.all_pincodes,
        customerType=request.customer_type,
    )
    pin = await resolve(service, f, export=True)
    # Raw authorship/notes stay office-only, including CSV audit.
    if request.include_audit:
        await service.require_office()
    raw = await observations(
        service, pin, request.cylinder_types, request.customer_type, start, end, active=False
    )
    benchmarks = {}
    for code in request.cylinder_types:
        _, entry = await service.benchmark(code, read_only=True)
        benchmarks[code] = entry.bpcl_base_rate + entry.tier_markup
    now = datetime.now(UTC)
    rows, latest = [], {}
    for log, brand in raw:
        rate = benchmarks[log.cylinder_type]
        gap = log.new_price - rate
        row = {
            "deliveryPincode": log.location_pincode,
            "hubAreaName": "",
            "customerSegment": log.customer_type,
            "cylinderType": LABELS[log.cylinder_type],
            "cylinderCode": log.cylinder_type,
            "competitorName": brand.name,
            "brandCode": brand.code,
            "quotedRate": float(log.new_price),
            "mbgaBenchmark": float(rate),
            "priceGap": float(gap),
            "variancePercentage": round(float(gap / rate * 100), 2) if rate else 0,
            "marketPosition": "Competitor Higher"
            if gap > 0
            else "Undercut Alert"
            if gap < 0
            else "At Par",
            "surveyDate": log.created_at,
            "effectiveDate": log.effective_date,
            "fromDate": start,
            "toDate": end,
            "generatedAt": now,
            "benchmarkBasis": "Current STANDARD rate",
        }
        if request.include_audit:
            row.update(
                recordedBy=log.changed_by_user_name,
                oldPrice=float(log.old_price),
                newPrice=float(log.new_price),
                notes=log.notes,
            )
        rows.append(row)
        if brand.status == "ACTIVE":
            latest[(log.location_pincode, log.cylinder_type, brand.id)] = row
    summary = sorted(
        latest.values(),
        key=lambda row: (
            row["deliveryPincode"],
            row["cylinderCode"],
            row["quotedRate"],
            row["brandCode"],
        ),
    )
    # Include an explicit benchmark row per observed market/cylinder.
    market_rows = {}
    for row in summary:
        key = row["deliveryPincode"], row["cylinderCode"]
        market_rows[key] = row | {
            "competitorName": "MBGA",
            "brandCode": "MBGA",
            "quotedRate": row["mbgaBenchmark"],
            "priceGap": 0,
            "variancePercentage": 0,
            "marketPosition": "At Par",
            "surveyDate": None,
            "effectiveDate": None,
        }
    summary = list(market_rows.values()) + summary
    columns = [
        "deliveryPincode",
        "hubAreaName",
        "customerSegment",
        "cylinderType",
        "cylinderCode",
        "competitorName",
        "brandCode",
        "quotedRate",
        "mbgaBenchmark",
        "priceGap",
        "variancePercentage",
        "marketPosition",
        "surveyDate",
        "effectiveDate",
        "fromDate",
        "toDate",
        "generatedAt",
        "benchmarkBasis",
    ]
    metadata = [
        {
            "pincode": pin or "ALL",
            "segment": request.customer_type,
            "fromDate": start,
            "toDate": end,
            "generatedAt": now,
            "benchmarkBasis": "Current STANDARD rate",
            "hubAreaName": "Not recorded for historical surveys",
        }
    ]
    if request.format == "CSV":
        selected = rows if request.include_audit else summary
        fields = columns + (
            ["recordedBy", "oldPrice", "newPrice", "notes"] if request.include_audit else []
        )
        payload, media, suffix = _csv(fields, fields, selected), "text/csv; charset=utf-8", "csv"
    else:
        sheets = [
            ("All_Pincodes_Comparison", columns, columns, summary),
            ("Report Metadata", list(metadata[0]), list(metadata[0]), metadata),
        ]
        if request.include_audit:
            fields = columns + ["recordedBy", "oldPrice", "newPrice", "notes"]
            sheets.append(("Audit_Log", fields, fields, rows))
        payload, media, suffix = (
            xlsx_workbook(sheets),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    return Response(
        payload,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="MBGA_Competitor_Pricing_{pin or "All_Pincodes"}_{start}_{end}.{suffix}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
