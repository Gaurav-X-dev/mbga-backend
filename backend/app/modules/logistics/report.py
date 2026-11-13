from dataclasses import dataclass
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Query
from sqlalchemy import func, or_, select

from app.modules.deliveries.models import DeliverySlipItem
from app.modules.logistics.models import Trip, TripStop
from app.modules.logistics.service import decode, trip_facts_many
from app.modules.merchants.models import Merchant
from app.modules.reports.schemas import DetailField, ReportRowDetail, StatusBadge
from app.shared.exceptions.api_error import ApiError


@dataclass
class TripReportFilters:
    vehicle: str | None = None
    driver_user_id: str | None = None
    trip_id: str | None = None
    status: str | None = None
    date_basis: str = "dispatch"
    discrepancies_only: bool = False


def trip_report_filters(
    trip_vehicle: Annotated[str | None, Query(alias="tripVehicle", max_length=50)] = None,
    trip_driver: Annotated[str | None, Query(alias="tripDriver", max_length=160)] = None,
    trip_id: Annotated[str | None, Query(alias="tripId", max_length=36)] = None,
    trip_status: Annotated[str | None, Query(alias="tripStatus", max_length=24)] = None,
    trip_date_basis: Annotated[
        str, Query(alias="tripDateBasis", pattern="^(dispatch|return|scheduled)$")
    ] = "dispatch",
    trip_discrepancies: Annotated[bool, Query(alias="tripDiscrepanciesOnly")] = False,
):
    return TripReportFilters(
        trip_vehicle, trip_driver, trip_id, trip_status, trip_date_basis, trip_discrepancies
    )


async def build_trip_report(service, start, end, customer_id):
    f = service.trip_filters or TripReportFilters()
    timestamp = (
        Trip.dispatched_at
        if f.date_basis == "dispatch"
        else Trip.returned_at
        if f.date_basis == "return"
        else Trip.scheduled_date
    )
    query = select(Trip)
    if service.merchant_id:
        query = query.where(Trip.merchant_id == service.merchant_id)
    low, high = (
        (
            start.astimezone(ZoneInfo("Asia/Kolkata")).date(),
            end.astimezone(ZoneInfo("Asia/Kolkata")).date(),
        )
        if f.date_basis == "scheduled"
        else (start, end)
    )
    query = query.where(timestamp >= low, timestamp <= high)
    if f.vehicle:
        query = query.where(Trip.vehicle_number == f.vehicle)
    if f.driver_user_id:
        query = query.where(
            or_(
                Trip.driver_user_id == f.driver_user_id,
                Trip.driver_name.ilike("%" + f.driver_user_id.strip() + "%"),
            )
        )
    if f.trip_id:
        query = query.where(Trip.id == f.trip_id)
    if f.status:
        query = query.where(Trip.status == f.status)
    if f.discrepancies_only:
        query = query.where(Trip.verification.is_not(None))
    trips = (
        await service.session.scalars(
            query.order_by(Trip.scheduled_date.desc(), Trip.id).limit(5001)
        )
    ).all()
    if len(trips) > 5000:
        raise ApiError(
            "TRIP_EXPORT_LIMIT",
            422,
            "Shorten the period or select a vehicle; this report is limited to 5,000 trips.",
        )
    if f.discrepancies_only:
        trips = [
            t
            for t in trips
            if any(
                d.get("filledDifference") or d.get("emptyDifference") or d.get("damaged")
                for d in decode(t.verification, {}).get("differences", [])
            )
        ]
    merchant_names = (
        dict(
            (
                await service.session.execute(
                    select(Merchant.id, Merchant.name).where(
                        Merchant.id.in_({t.merchant_id for t in trips})
                    )
                )
            ).all()
        )
        if trips
        else {}
    )
    ids = [t.id for t in trips]
    stop_count = (
        await service.session.scalar(
            select(func.count()).select_from(TripStop).where(TripStop.trip_id.in_(ids))
        )
        if ids
        else 0
    )
    line_count = (
        await service.session.scalar(
            select(func.count())
            .select_from(DeliverySlipItem)
            .join(TripStop, TripStop.delivery_id == DeliverySlipItem.slip_id)
            .where(TripStop.trip_id.in_(ids))
        )
        if ids
        else 0
    )
    if stop_count > 10000 or line_count > 50000:
        raise ApiError(
            "TRIP_EXPORT_LIMIT",
            422,
            "Shorten the period; the matching delivery detail is too large.",
        )
    data = await trip_facts_many(service.session, ids)
    columns = [
        ("merchant", "Merchant"),
        ("trip", "Trip"),
        ("date", "Scheduled date"),
        ("vehicle", "Vehicle"),
        ("driver", "Driver"),
        ("status", "Status"),
        ("cylinderType", "Cylinder"),
        ("loadedFilled", "Filled loaded"),
        ("delivered", "Delivered"),
        ("pending", "Pending demand"),
        ("unfulfilled", "Unfulfilled demand"),
        ("expectedFilled", "Expected filled return"),
        ("receivedFilled", "Verified filled return"),
        ("expectedEmpty", "Expected empty return"),
        ("receivedEmpty", "Verified empty return"),
        ("damaged", "Filled returned damaged"),
        ("difference", "Count difference"),
    ]
    rows = []
    summaries = []
    stops = []
    discrepancies = []
    for trip in trips:
        pairs, facts = data[trip.id]
        verified = decode(trip.verification, {})
        received = {c["cylinderType"]: c for c in verified.get("counts", [])}
        summary = {
            "trip": trip.number,
            "merchant": merchant_names.get(trip.merchant_id, trip.merchant_id),
            "date": str(trip.scheduled_date),
            "vehicle": trip.vehicle_number,
            "driver": trip.driver_name,
            "status": trip.status,
            "dispatchedAt": str(trip.dispatched_at) if trip.dispatched_at else None,
            "returnedAt": str(trip.returned_at) if trip.returned_at else None,
            "startOdometer": trip.start_odometer,
            "endOdometer": trip.end_odometer,
            "verifiedBy": trip.verified_by,
            "verifiedAt": str(trip.verified_at) if trip.verified_at else None,
        }
        summaries.append(summary)
        for code, line in facts.items():
            actual = received.get(code)
            difference = (
                actual["filled"]
                + actual["empty"]
                + actual.get("damaged", 0)
                - line["expectedFilled"]
                - line["expectedEmpty"]
                if actual
                else None
            )
            row = {
                **summary,
                "cylinderType": code,
                **line,
                "receivedFilled": actual["filled"] if actual else None,
                "receivedEmpty": actual["empty"] if actual else None,
                "damaged": actual.get("damaged", 0) if actual else None,
                "difference": difference,
            }
            if actual and (
                actual["filled"] + actual.get("damaged", 0) != line["expectedFilled"]
                or actual["empty"] != line["expectedEmpty"]
                or actual.get("damaged", 0)
            ):
                discrepancies.append({k: v for k, v in row.items()})
            row["id"] = f"{trip.id}:{code}"
            row["detail"] = ReportRowDetail(
                id=row["id"],
                title=summary["trip"],
                subtitle=f"{trip.vehicle_number} · {trip.driver_name}",
                statusBadge=StatusBadge(
                    label=trip.status,
                    color="warning" if trip.status == "DISCREPANCY" else "neutral",
                ),
                fields=[DetailField(label=label, value=row.get(key)) for key, label in columns],
                notes=verified.get("reason") or trip.notes,
            ).model_dump(by_alias=True, mode="json")
            rows.append(row)
        for stop, slip in pairs:
            stops.append(
                {
                    "trip": summary["trip"],
                    "sequence": stop.sequence,
                    "order": slip.order_number,
                    "customer": slip.customer_name,
                    "status": slip.status,
                    "vehicle": trip.vehicle_number,
                    "items": slip.items_summary,
                    "deliveredAt": str(slip.delivered_at) if slip.delivered_at else None,
                }
            )
    if len(rows) > 10000:
        raise ApiError(
            "TRIP_EXPORT_LIMIT", 422, "Shorten the period; the report exceeds 10,000 cylinder rows."
        )
    sheets = [
        {
            "name": "Trip Summary",
            "columns": [
                "trip",
                "merchant",
                "date",
                "vehicle",
                "driver",
                "status",
                "dispatchedAt",
                "returnedAt",
                "startOdometer",
                "endOdometer",
                "verifiedBy",
                "verifiedAt",
            ],
            "rows": summaries,
        },
        {
            "name": "Dispatch and Returns",
            "columns": [key for key, _ in columns],
            "labels": [label for _, label in columns],
            "rows": [{k: v for k, v in row.items() if k not in ("detail", "id")} for row in rows],
        },
        {
            "name": "Delivery Stops",
            "columns": [
                "trip",
                "sequence",
                "order",
                "customer",
                "status",
                "vehicle",
                "items",
                "deliveredAt",
            ],
            "rows": stops,
        },
        {
            "name": "Discrepancies",
            "columns": [key for key, _ in columns],
            "labels": [label for _, label in columns],
            "rows": discrepancies,
        },
    ]
    return (
        [
            ("Trips", len(trips)),
            ("Filled loaded", sum(r["loadedFilled"] for r in rows)),
            ("Delivered", sum(r["delivered"] for r in rows)),
            (
                "Awaiting reconciliation",
                sum(t.status in ("RETURNED", "DISCREPANCY") for t in trips),
            ),
        ],
        [
            {
                "key": k,
                "label": v,
                "align": "right"
                if k
                in (
                    "loadedFilled",
                    "delivered",
                    "unfulfilled",
                    "expectedFilled",
                    "receivedFilled",
                    "expectedEmpty",
                    "receivedEmpty",
                    "difference",
                    "damaged",
                )
                else "left",
            }
            for k, v in columns
        ],
        rows,
        {
            "dateBasis": f.date_basis,
            "coverage": "Trip records captured after logistics deployment. Historical depot returns are not inferred. Blank received counts mean not verified.",
            "exportSheets": sheets,
        },
    )
