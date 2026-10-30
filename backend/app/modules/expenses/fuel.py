"""Optional fuel telemetry; legacy expenses without telemetry remain valid."""
from decimal import Decimal
from sqlalchemy import select
from app.modules.vehicles.models import Vehicle
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.users.models import User
from app.modules.expenses.validation import invalid
from app.modules.expenses.models import ExpenseFuelType

FIELDS = ("vehicle_id", "driver_id", "fuel_type", "km_reading", "distance", "liters")


async def apply_fuel(session, merchant_id, expense, category, payload):
    supplied = payload.model_fields_set.intersection(FIELDS)
    if category.code != "FUEL" and category.icon != "fuel":
        if any(getattr(payload, field) is not None for field in supplied):
            raise invalid("categoryId", "invalid", "Fuel details require a Fuel category.")
        for field in (*FIELDS, "vehicle_number", "driver_name"):
            setattr(expense, field, None)
        return
    if not supplied:
        return
    values = {field: getattr(payload, field) if field in supplied else getattr(expense, field, None) for field in FIELDS}
    for field in FIELDS:
        if values[field] is None or values[field] == "":
            raise invalid(field, "required", "Complete the fuel details.")
    fuel_type = await session.get(ExpenseFuelType, values["fuel_type"])
    if fuel_type is None or (not fuel_type.is_active and values["fuel_type"] != expense.fuel_type):
        raise invalid("fuelType", "invalid", "Choose an available fuel type.")
    for field in ("km_reading", "distance", "liters"):
        value = Decimal(values[field])
        if not value.is_finite() or value < 0 or (field != "km_reading" and value == 0) or value > Decimal("999999999.99"):
            raise invalid(field, "invalid", "Enter a valid positive reading.")
    vehicle = await session.get(Vehicle, values["vehicle_id"])
    driver = await session.get(DeliveryProfile, values["driver_id"])
    if vehicle is None or vehicle.merchant_id != merchant_id or (not vehicle.is_active and vehicle.id != expense.vehicle_id):
        raise invalid("vehicleId", "invalid", "Choose a vehicle from this merchant.")
    if driver is None or driver.merchant_id != merchant_id or driver.delivery_user_type != "DRIVER" or (driver.status != "ACTIVE" and driver.id != expense.driver_id):
        raise invalid("driverId", "invalid", "Choose a driver from this merchant.")
    user = await session.get(User, driver.user_id)
    for field, value in values.items():
        setattr(expense, field, value)
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
