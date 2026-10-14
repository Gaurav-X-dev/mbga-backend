"""Pincode-wise grouping for the merchant bulk assignment sheet."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.modules.customers.models import CustomerProfile
from app.modules.orders.models import Order
from app.modules.vehicles.models import Vehicle, VehiclePincodeMapping
from tests.integration.orders.conftest import (
    ORDERS,
    created_order,
    make_customer,
    order_staff,
    post,
    settings_overrides,  # noqa: F401
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

ASSIGNMENT_PERMISSIONS = (
    "orders.view",
    "orders.create",
    "orders.update",
    "orders.cancel",
    "pricing.view",
    "pricing.manage",
)


async def _mapped_vehicle(env, merchant_id: str, pincode: str, number: str) -> Vehicle:
    now = datetime.now(UTC)
    vehicle = Vehicle(
        id=str(uuid4()),
        merchant_id=merchant_id,
        number=number,
        label=f"Vehicle for {pincode}",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    async with env.sessions() as db:
        db.add(vehicle)
        await db.flush()
        db.add(
            VehiclePincodeMapping(
                id=str(uuid4()),
                merchant_id=merchant_id,
                vehicle_id=vehicle.id,
                pincode=pincode,
                priority=0,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()
    return vehicle


async def test_preview_groups_orders_and_filters_vehicles_by_pincode(env):
    token, merchant, _user = await order_staff(env, permissions=ASSIGNMENT_PERMISSIONS)
    first_customer = await make_customer(env, merchant)
    second_customer = await make_customer(env, merchant)
    async with env.sessions() as db:
        await db.execute(
            update(CustomerProfile)
            .where(CustomerProfile.id == second_customer.id)
            .values(address_pincode="452002", address_city="Indore")
        )
        await db.commit()
    first = await created_order(env, token, first_customer.id)
    second = await created_order(env, token, second_customer.id)
    first_van = await _mapped_vehicle(env, merchant.id, "452001", "MP09 AA 0001")
    second_van = await _mapped_vehicle(env, merchant.id, "452002", "MP09 BB 0002")

    response = await post(
        env,
        f"{ORDERS}/bulk-assignment/preview",
        token,
        {"orderIds": [second["id"], first["id"]]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selectedOrderCount"] == 2
    assert body["groupCount"] == 2
    by_pin = {group["pincode"]: group for group in body["groups"]}
    assert [row["id"] for row in by_pin["452001"]["orders"]] == [first["id"]]
    assert {row["id"] for row in by_pin["452001"]["availableVehicles"]} == {first_van.id}
    assert {row["id"] for row in by_pin["452002"]["availableVehicles"]} == {second_van.id}
    assert all(group["canAssign"] for group in body["groups"])


async def test_grouped_confirm_rejects_orders_from_different_pincodes_in_one_group(env):
    token, merchant, _user = await order_staff(env, permissions=ASSIGNMENT_PERMISSIONS)
    first_customer = await make_customer(env, merchant)
    second_customer = await make_customer(env, merchant)
    async with env.sessions() as db:
        await db.execute(
            update(CustomerProfile)
            .where(CustomerProfile.id == second_customer.id)
            .values(address_pincode="452002")
        )
        await db.commit()
    first = await created_order(env, token, first_customer.id)
    second = await created_order(env, token, second_customer.id)

    response = await post(
        env,
        f"{ORDERS}/bulk-assignment/confirm",
        token,
        {
            "groups": [
                {
                    "orderIds": [first["id"], second["id"]],
                    "delivery": {"vehicleNumber": "MP09 AA 0001", "driverName": "Driver"},
                }
            ]
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "MIXED_PINCODE_ASSIGNMENT"
    async with env.sessions() as db:
        rows = await db.execute(
            select(Order.status).where(Order.id.in_([first["id"], second["id"]]))
        )
        assert set(rows.scalars()) == {"PLACED"}
