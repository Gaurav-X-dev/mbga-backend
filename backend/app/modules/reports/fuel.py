"""Fuel-sheet reports: expense-backed rows and identical screen/export filters."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated
from fastapi import Query
from sqlalchemy import select, or_, func
from app.modules.expenses.models import Expense, ExpenseCategory, ExpenseFuelType
from app.shared.date_time.business_calendar import IST_TIMEZONE
from app.shared.exceptions.api_error import ApiError
from app.modules.vehicles.models import Vehicle
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.users.models import User
from app.modules.merchants.models import MerchantUser


@dataclass
class FuelFilters:
    values: dict = field(default_factory=dict)

    def apply(self, statement):
        for key, column in [("vehicle_id",Expense.vehicle_id),("driver_id",Expense.driver_id),("fuel_type",Expense.fuel_type),("recorded_by",Expense.recorded_by_user_id)]:
            if self.values.get(key): statement = statement.where(column == self.values[key])
        for key, column in [("destination",Expense.destination),("search",None)]:
            if self.values.get(key):
                term = "%" + self.values[key].strip() + "%"
                statement = statement.where(column.ilike(term) if column is not None else or_(Expense.note.ilike(term),Expense.vehicle_number.ilike(term),Expense.driver_name.ilike(term),Expense.destination.ilike(term),Expense.recorded_by_name.ilike(term)))
        if self.values.get("has_receipt") is not None:
            statement = statement.where(Expense.receipt_storage_key.is_not(None) if self.values["has_receipt"] else Expense.receipt_storage_key.is_(None))
        if self.values.get("telemetry") == "complete":
            statement = statement.where(Expense.distance.is_not(None),Expense.liters > 0)
        elif self.values.get("telemetry") == "missing":
            statement = statement.where(or_(Expense.distance.is_(None),Expense.liters.is_(None),Expense.liters <= 0))
        for name, column in [("amount",Expense.amount),("kmReading",Expense.km_reading),("distance",Expense.distance),("liters",Expense.liters),("mileage",Expense.distance / func.nullif(Expense.liters,0))]:
            lower, upper = self.values.get("min"+name[0].upper()+name[1:]), self.values.get("max"+name[0].upper()+name[1:])
            if lower is not None: statement = statement.where(column >= lower)
            if upper is not None: statement = statement.where(column <= upper)
        return statement


def fuel_filter_params(
    vehicle_id: Annotated[str | None, Query(alias="vehicleId", max_length=160)] = None,
    driver_id: Annotated[str | None, Query(alias="driverId", max_length=160)] = None,
    fuel_type: Annotated[str | None, Query(alias="fuelType", max_length=160)] = None,
    recorded_by: Annotated[str | None, Query(alias="recordedBy", max_length=160)] = None,
    destination: Annotated[str | None, Query(alias="destination", max_length=160)] = None,
    search: Annotated[str | None, Query(alias="search", max_length=160)] = None,
    has_receipt: Annotated[bool | None, Query(alias="hasReceipt")] = None,
    telemetry: Annotated[str | None, Query(pattern="^(complete|missing)$")] = None,
    minAmount: Annotated[Decimal | None, Query(ge=0)] = None,
    maxAmount: Annotated[Decimal | None, Query(ge=0)] = None,
    minKmReading: Annotated[Decimal | None, Query(ge=0)] = None,
    maxKmReading: Annotated[Decimal | None, Query(ge=0)] = None,
    minDistance: Annotated[Decimal | None, Query(ge=0)] = None,
    maxDistance: Annotated[Decimal | None, Query(ge=0)] = None,
    minLiters: Annotated[Decimal | None, Query(ge=0)] = None,
    maxLiters: Annotated[Decimal | None, Query(ge=0)] = None,
    minMileage: Annotated[Decimal | None, Query(ge=0)] = None,
    maxMileage: Annotated[Decimal | None, Query(ge=0)] = None,
 ) -> FuelFilters:
    values = locals().copy()
    for name in ["Amount","KmReading","Distance","Liters","Mileage"]:
        low, high = values.get("min"+name), values.get("max"+name)
        if low is not None and high is not None and low > high:
            raise ApiError("VALIDATION_ERROR",422,f"Minimum {name} must not exceed maximum.")
    return FuelFilters(values)


async def build_fuel_report(service, start, end):
    # spent_on is an Indian calendar DATE, rather than a UTC instant.
    base = select(Expense).join(ExpenseCategory,ExpenseCategory.id == Expense.category_id).where(
        *service._merchant_filter(Expense.merchant_id),
        or_(ExpenseCategory.code == "FUEL", ExpenseCategory.icon == "fuel"),
        Expense.spent_on.between(start.astimezone(IST_TIMEZONE).date(),end.astimezone(IST_TIMEZONE).date()))
    # Dropdowns are independent of report dates and current fuel transactions.
    # Historical snapshots retain retired/deleted records; master rows add people and
    # vehicles that have never appeared in a fuel expense.
    option_source = select(Expense).join(ExpenseCategory, ExpenseCategory.id == Expense.category_id).where(
        *service._merchant_filter(Expense.merchant_id),
        or_(ExpenseCategory.code == "FUEL", ExpenseCategory.icon == "fuel"))
    options_rows = (await service.session.execute(option_source.with_only_columns(Expense.vehicle_id,Expense.vehicle_number,Expense.driver_id,Expense.driver_name,Expense.recorded_by_user_id,Expense.recorded_by_name).distinct())).all()
    fuel_types = (await service.session.scalars(select(ExpenseFuelType).order_by(ExpenseFuelType.sort_order, ExpenseFuelType.label))).all()
    options = {"vehicles":{},"drivers":{},"recorders":{},"fuelTypes":{item.code:item.label for item in fuel_types}}
    for vehicle_id, vehicle, driver_id, driver, recorder_id, recorder in options_rows:
        if vehicle_id: options["vehicles"][vehicle_id] = vehicle or vehicle_id
        if driver_id: options["drivers"][driver_id] = driver or driver_id
        if recorder_id: options["recorders"][recorder_id] = recorder or recorder_id
    vehicles = (await service.session.scalars(select(Vehicle).where(
        *service._merchant_filter(Vehicle.merchant_id)).order_by(Vehicle.number, Vehicle.id))).all()
    for vehicle in vehicles:
        options["vehicles"][vehicle.id] = vehicle.number
    drivers = (await service.session.execute(select(DeliveryProfile.id, User.full_name).join(
        User, User.id == DeliveryProfile.user_id).where(
            *service._merchant_filter(DeliveryProfile.merchant_id),
            DeliveryProfile.delivery_user_type == "DRIVER").order_by(User.full_name, DeliveryProfile.id))).all()
    for driver_id, name in drivers:
        options["drivers"][driver_id] = name or driver_id
    staff = (await service.session.execute(select(User.id, User.full_name).join(
        MerchantUser, MerchantUser.user_id == User.id).where(
            *service._merchant_filter(MerchantUser.merchant_id)).distinct())).all()
    for staff_id, name in staff:
        options["recorders"][staff_id] = name or staff_id
    statement = (service.fuel_filters or FuelFilters()).apply(base)
    records = list((await service.session.scalars(statement.order_by(Expense.spent_on,Expense.km_reading,Expense.id).limit(5001))).all())
    if len(records) > 5000:
        raise ApiError("REPORT_RANGE_TOO_LARGE",422,"Fuel report exceeds 5,000 entries. Narrow the date range or filters before viewing or exporting.")
    rows=[]
    for expense in records:
        mileage = float(expense.distance / expense.liters) if expense.distance is not None and expense.liters else None
        rows.append({"id":expense.id,"date":expense.spent_on.isoformat(),**service._merchant_fields(expense.merchant_id),
            "vehicle":expense.vehicle_number,"kmReading":float(expense.km_reading) if expense.km_reading is not None else None,
            "fuelType":expense.fuel_type,"liters":float(expense.liters) if expense.liters is not None else None,
            "distance":float(expense.distance) if expense.distance is not None else None,"mileage":round(mileage,2) if mileage is not None else None,
            "amount":float(expense.amount),"driver":expense.driver_name,"destination":expense.destination,
            "recordedBy":expense.recorded_by_name,"receipt":"Attached" if expense.receipt_storage_key else "None","note":expense.note})
    paired=[e for e in records if e.distance is not None and e.liters and e.liters > 0]
    distance=sum((e.distance for e in paired),Decimal(0));liters=sum((e.liters for e in paired),Decimal(0))
    total_liters=sum((e.liters or Decimal(0) for e in records),Decimal(0))
    total_distance=sum((e.distance or Decimal(0) for e in records),Decimal(0))
    summary=[("Fuel spend",float(sum((e.amount for e in records),Decimal(0)))),("Entries",len(records)),("Fuel (L)",float(total_liters)),("Distance (km)",float(total_distance)),("Average (km/L)",round(float(distance/liters),2) if liters else "—")]
    columns=service._columns(("date","Date"),("vehicle","Vehicle"),("kmReading","KM Reading","right"),("fuelType","Fuel Type"),("liters","Fuel (L)","right"),("distance","Distance (km)","right"),("mileage","Avg. (km/L)","right"),("amount","Amount (₹)","right"),("driver","Driver"),("destination","Destination"),("recordedBy","Recorded By"),("receipt","Receipt"),("note","Note"))
    return summary,columns,rows,{"truncated":False,"fuelOptions":{key:[{"value":value,"label":label} for value,label in sorted(items.items(),key=lambda pair:pair[1])] for key,items in options.items()},"basis":"Fuel expense records; overall mileage = total distance / total liters for records containing both values."}


async def fuel_all_time_range(session, merchant_id):
    from datetime import datetime, time
    from app.shared.date_time.business_calendar import business_today
    statement = select(func.min(Expense.spent_on),func.max(Expense.spent_on)).join(ExpenseCategory,ExpenseCategory.id==Expense.category_id).where(or_(ExpenseCategory.code=="FUEL",ExpenseCategory.icon=="fuel"))
    if merchant_id:
        statement = statement.where(Expense.merchant_id==merchant_id)
    earliest, latest = (await session.execute(statement)).one()
    return datetime.combine(earliest or business_today(),time.min,tzinfo=IST_TIMEZONE), datetime.combine(latest or business_today(),time.max,tzinfo=IST_TIMEZONE)
