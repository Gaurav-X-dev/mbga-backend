"""Optional fuel telemetry; legacy expenses without telemetry remain valid."""
from decimal import Decimal

from sqlalchemy import select

from app.modules.delivery_users.models import DeliveryProfile
from app.modules.expenses.models import Expense, ExpenseFuelType
from app.modules.expenses.validation import invalid
from app.modules.users.models import User
from app.modules.vehicles.models import Vehicle

FIELDS = ("vehicle_id", "driver_id", "fuel_type", "start_odometer", "end_odometer", "liters")


async def apply_fuel(session, merchant_id, expense, category, payload):
    supplied = payload.model_fields_set.intersection(FIELDS)
    if category.code != "FUEL" and category.icon != "fuel":
        if any(getattr(payload, field) is not None for field in supplied):
            raise invalid("categoryId", "invalid", "Fuel details require a Fuel category.")
        for field in (*FIELDS, "km_reading", "distance", "vehicle_number", "driver_name"):
            setattr(expense, field, None)
        return
    if not supplied:
        return
    values = {field: getattr(payload, field) if field in supplied else getattr(expense, field, None) for field in FIELDS}
    for field in ("vehicle_id", "driver_id", "fuel_type", "start_odometer", "end_odometer"):
        if values[field] is None or values[field] == "":
            raise invalid(field, "required", "Complete the fuel details.")
    fuel_type = await session.get(ExpenseFuelType, values["fuel_type"])
    if fuel_type is None or (not fuel_type.is_active and values["fuel_type"] != expense.fuel_type):
        raise invalid("fuelType", "invalid", "Choose an available fuel type.")
    for field in ("start_odometer", "end_odometer"):
        value = Decimal(values[field])
        if not value.is_finite() or value < 0 or value > Decimal("999999999.99"):
            raise invalid(field, "invalid", "Enter a valid positive reading.")
    start, end = Decimal(values["start_odometer"]), Decimal(values["end_odometer"])
    if end < start:
        raise invalid("endOdometer", "invalid", "Ending odometer cannot be less than starting odometer.")
    if values["liters"] not in (None, ""):
        liters = Decimal(values["liters"])
        if not liters.is_finite() or liters <= 0:
            raise invalid("liters", "invalid", "Fuel consumed must be greater than zero.")
    duplicate = await session.scalar(select(Expense.id).where(
        Expense.merchant_id == merchant_id, Expense.vehicle_id == values["vehicle_id"],
        Expense.spent_on == expense.spent_on, Expense.id != expense.id,
    ).with_for_update())
    if duplicate:
        raise invalid("vehicleId", "duplicate", "A daily fuel entry already exists for this vehicle.")
    previous_end = await session.scalar(select(Expense.end_odometer).where(
        Expense.merchant_id == merchant_id, Expense.vehicle_id == values["vehicle_id"],
        Expense.spent_on < expense.spent_on, Expense.end_odometer.is_not(None),
    ).order_by(Expense.spent_on.desc()).limit(1).with_for_update())
    if previous_end is not None and start < Decimal(previous_end):
        raise invalid("startOdometer", "invalid", f"Starting odometer cannot be below the previous ending reading ({previous_end}).")
    vehicle = await session.get(Vehicle, values["vehicle_id"])
    driver = await session.get(DeliveryProfile, values["driver_id"])
    if vehicle is None or vehicle.merchant_id != merchant_id or (not vehicle.is_active and vehicle.id != expense.vehicle_id):
        raise invalid("vehicleId", "invalid", "Choose a vehicle from this merchant.")
    if driver is None or driver.merchant_id != merchant_id or driver.delivery_user_type != "DRIVER" or (driver.status != "ACTIVE" and driver.id != expense.driver_id):
        raise invalid("driverId", "invalid", "Choose a driver from this merchant.")
    user = await session.get(User, driver.user_id)
    for field, value in values.items():
        setattr(expense, field, value)
    expense.km_reading = end
    expense.distance = end - start
    expense.vehicle_number = vehicle.number
    expense.driver_name = (user.full_name or driver.id) if user else driver.id


async def fuel_options(session, merchant_id):
    vehicles = (await session.scalars(select(Vehicle).where(Vehicle.merchant_id == merchant_id, Vehicle.is_active.is_(True)).order_by(Vehicle.number))).all()
    drivers = (await session.execute(select(DeliveryProfile.id, User.full_name).join(User, User.id == DeliveryProfile.user_id).where(
        DeliveryProfile.merchant_id == merchant_id, DeliveryProfile.status == "ACTIVE", DeliveryProfile.delivery_user_type == "DRIVER"
    ).order_by(User.full_name))).all()
    types = (await session.scalars(select(ExpenseFuelType).where(ExpenseFuelType.is_active.is_(True)).order_by(ExpenseFuelType.sort_order, ExpenseFuelType.label))).all()
    return {"fuelTypes": [{"value": item.code, "label": item.label} for item in types], "vehicles": [{"value": v.id, "label": v.number} for v in vehicles],
            "drivers": [{"value": d.id, "label": d.full_name or d.id} for d in drivers]}
