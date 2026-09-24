"""Create idempotent local-only data for manual Delivery App API testing.

This script never deletes data. It creates or reuses a clearly labelled demo
merchant, driver, delivery, inventory, notification, and payment records.
Run it only against a local/development database.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.models import Delivery
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.inventory.models import DriverInventory
from app.modules.merchants.models import Merchant
from app.modules.notifications.models import Notification
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.models import PaymentMethod, PaymentTransaction
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RolePermission
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.database.session import AsyncSessionLocal

PHONE = "+919876543210"
MERCHANT_CODE = "TEST_DELIVERY_MERCHANT"
ORDER_NUMBER = "TEST-DELIVERY-001"


async def main() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        merchant = await session.scalar(select(Merchant).where(Merchant.code == MERCHANT_CODE))
        if merchant is None:
            merchant = Merchant(
                id=str(uuid4()), code=MERCHANT_CODE, name="Delivery API Demo Merchant",
                mobile_number=None, status="ACTIVE", approval_status="APPROVED", created_by=None,
                created_at=now, updated_at=now,
            )
            session.add(merchant)

        user = await session.scalar(select(User).where(User.mobile_number == PHONE))
        if user is None:
            user = User(
                id=str(uuid4()), username="delivery_demo_driver", full_name="Delivery Demo Driver",
                email=None, mobile_number=PHONE, country_code="+91", password_hash=None,
                role="driver", status="ACTIVE", created_at=now, updated_at=now,
            )
            session.add(user)
        await session.flush()

        role = await session.scalar(select(Role).where(Role.code == "driver"))
        permission = await session.scalar(select(Permission).where(Permission.code == "deliveries.view"))
        if role is None or permission is None:
            raise RuntimeError("RBAC data is missing. Run `python scripts/seed_rbac.py` first.")
        if await session.get(RolePermission, {"role_id": role.id, "permission_id": permission.id}) is None:
            session.add(RolePermission(role_id=role.id, permission_id=permission.id, granted_at=now, granted_by=None))
        assignment = await session.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id))
        if assignment is None:
            session.add(UserRole(
                id=str(uuid4()), user_id=user.id, role_id=role.id, assigned_at=now, assigned_by=None,
                valid_from=now, valid_until=None, is_active=True, scope_type="global", scope_id="global",
            ))

        profile = await session.scalar(select(DeliveryProfile).where(DeliveryProfile.user_id == user.id))
        if profile is None:
            session.add(DeliveryProfile(
                id=str(uuid4()), merchant_id=merchant.id, user_id=user.id, delivery_user_type="DRIVER",
                status="ACTIVE", approval_status="APPROVED", vehicle_number="TEST-001", on_duty=True,
                language_code="en", created_at=now, updated_at=now,
            ))

        customer = await session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == "+919876543211"))
        if customer is None:
            customer = CustomerProfile(
                id=str(uuid4()), user_id=None, merchant_id=merchant.id, merchant_code=merchant.code,
                customer_type="INDUSTRIAL", mobile_number="+919876543211", name="Delivery Demo Customer",
                gst_number=None, status="APPROVED", rejection_reason=None, mobile_verified_at=now,
                submitted_at=now, reviewed_by=None, reviewed_at=now, created_at=now, updated_at=now,
            )
            session.add(customer)
        await session.flush()

        order = await session.scalar(select(Order).where(Order.order_number == ORDER_NUMBER))
        if order is None:
            order = Order(
                id=str(uuid4()), order_number=ORDER_NUMBER, merchant_id=merchant.id,
                customer_profile_id=customer.id, customer_name=customer.name or "Delivery Demo Customer",
                customer_phone=customer.mobile_number, address="MBGA Delivery API Demo Address",
                address_latitude=28.5710, address_longitude=77.3620, time_slot_start="10:00 AM",
                time_slot_end="12:00 PM", status="pending", distance_km=1.8, completed_at=None,
                notes=None, created_at=now, updated_at=now,
            )
            session.add(order)
            await session.flush()
            session.add_all([
                OrderItem(id=str(uuid4()), order_id=order.id, kind="cylinderDelivery", label="19 KG Cylinder", quantity=5),
                OrderItem(id=str(uuid4()), order_id=order.id, kind="emptyCollection", label="Empty Cylinders to Collect", quantity=5),
            ])

        delivery = await session.scalar(select(Delivery).where(Delivery.order_id == order.id, Delivery.driver_user_id == user.id))
        if delivery is None:
            delivery = Delivery(
                id=str(uuid4()), order_id=order.id, driver_user_id=user.id, merchant_id=merchant.id,
                status="pending", delivered_quantity=None, empty_collected_quantity=None,
                driver_latitude=None, driver_longitude=None, distance_meters_from_destination=None,
                customer_otp_hash=None, customer_otp_expires_at=None, notes=None, started_at=None,
                confirmed_at=None, completed_at=None, created_at=now, updated_at=now,
            )
            session.add(delivery)

        inventory = await session.scalar(select(DriverInventory).where(DriverInventory.driver_user_id == user.id))
        if inventory is None:
            session.add(DriverInventory(
                id=str(uuid4()), driver_user_id=user.id, merchant_id=merchant.id, full_cylinder_count=20,
                empty_cylinder_count=0, vehicle_capacity=30, last_updated_at=now,
            ))
        if await session.scalar(select(PaymentMethod).where(PaymentMethod.user_id == user.id)) is None:
            session.add(PaymentMethod(id=str(uuid4()), user_id=user.id, type="cash", label="Cash on Delivery", is_default=True, created_at=now))
        if await session.scalar(select(PaymentTransaction).where(PaymentTransaction.user_id == user.id)) is None:
            session.add(PaymentTransaction(id=str(uuid4()), user_id=user.id, order_id=order.id, amount=1000.0, status="completed", created_at=now))
        if await session.scalar(select(Notification).where(Notification.user_id == user.id)) is None:
            session.add(Notification(id=str(uuid4()), user_id=user.id, type="new_delivery", title="New Delivery Assigned", subtitle=f"#{ORDER_NUMBER}", is_read=False, created_at=now))

        await session.commit()
        print("Delivery API demo data is ready.")
        print(f"Driver phone: {PHONE}")
        print(f"Order number: {ORDER_NUMBER}")
        print(f"Delivery ID: {delivery.id}")


if __name__ == "__main__":
    asyncio.run(main())
