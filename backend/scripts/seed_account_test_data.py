import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config.app import get_settings
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.constants import LoginChannel
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.roles.models import Role
from app.modules.roles.seed_runner import RBACSeedRunner
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.database.session import AsyncSessionLocal


TEST_TAG = "MBGA_ACCOUNT_HANDOFF_TEST"

# Development-only numbers from the reserved +91 99999 000xx block (valid Indian mobile format).
DEFAULT_TEST_MOBILES = {
    "admin": "+919999900001",
    "merchant": "+919999900002",
    "driver": "+919999900003",
    "helper": "+919999900004",
}
# Numbers used by earlier versions of this script; they fail mobile validation.
LEGACY_TEST_MOBILES = {
    "admin": "+910000000001",
    "merchant": "+910000000002",
    "driver": "+910000000003",
    "helper": "+910000000004",
}


def _refuse_unsafe_environment() -> None:
    settings = get_settings()
    if settings.app_env.lower() not in {"local", "development", "test"}:
        raise SystemExit("Refusing to seed account test data outside local/development/test.")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _safe_email(prefix: str, mobile: str) -> str:
    suffix = "".join(ch for ch in mobile if ch.isdigit())
    return f"{prefix}.{suffix}@example.invalid"


async def _role(session, code: str) -> Role:
    role = await session.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise RuntimeError(f"Missing seeded role: {code}")
    return role


async def _user(session, *, mobile: str, name: str, role_code: str, email: str | None = None) -> User:
    user = await session.scalar(select(User).where(User.mobile_number == mobile))
    now = datetime.now(UTC)
    if user:
        user.status = "ACTIVE"
        user.full_name = name
        user.email = email
        user.updated_at = now
        return user
    user = User(
        id=str(uuid4()),
        email=email,
        username=None,
        full_name=name,
        mobile_number=mobile,
        country_code="+91",
        password_hash=None,
        role=role_code,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user


async def _assign(session, user: User, role_code: str, scope_type: str = "global", scope_id: str = "global") -> None:
    role = await _role(session, role_code)
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
            UserRole.scope_type == scope_type,
            UserRole.scope_id == scope_id,
        )
    )
    if existing:
        existing.is_active = True
        existing.valid_until = None
        return
    session.add(
        UserRole(
            id=str(uuid4()),
            user_id=user.id,
            role_id=role.id,
            assigned_at=datetime.now(UTC),
            assigned_by=None,
            valid_from=None,
            valid_until=None,
            is_active=True,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    )


def _mobile(name: str, default: str) -> str:
    value = _env(name, default)
    try:
        return normalize_mobile_number(value)
    except ValueError as exc:
        raise SystemExit(f"{name} is not a valid Indian mobile number.") from exc


async def _move_legacy_test_mobile(session, legacy: str, target: str) -> None:
    """Earlier versions seeded +91 0000 00000x numbers, which fail mobile validation.

    Move those seeded test users to the valid number, but only when the target is unused.
    """
    if legacy == target or await session.scalar(select(User).where(User.mobile_number == target)):
        return
    user = await session.scalar(select(User).where(User.mobile_number == legacy))
    if user is not None:
        user.mobile_number = target
        user.updated_at = datetime.now(UTC)


async def main() -> None:
    _refuse_unsafe_environment()
    admin_mobile = _mobile("MBGA_TEST_SUPER_ADMIN_MOBILE", DEFAULT_TEST_MOBILES["admin"])
    merchant_mobile = _mobile("MBGA_TEST_MERCHANT_MOBILE", DEFAULT_TEST_MOBILES["merchant"])
    driver_mobile = _mobile("MBGA_TEST_DRIVER_MOBILE", DEFAULT_TEST_MOBILES["driver"])
    helper_mobile = _mobile("MBGA_TEST_HELPER_MOBILE", DEFAULT_TEST_MOBILES["helper"])
    async with AsyncSessionLocal() as session:
        await RBACSeedRunner(session).run()
        for key, target in {
            "admin": admin_mobile,
            "merchant": merchant_mobile,
            "driver": driver_mobile,
            "helper": helper_mobile,
        }.items():
            await _move_legacy_test_mobile(session, LEGACY_TEST_MOBILES[key], target)
        await session.flush()
        admin = await _user(session, mobile=admin_mobile, name="Test Super Admin", role_code="super_admin", email=_safe_email("superadmin.test", admin_mobile))
        await _assign(session, admin, "super_admin")

        merchant_user = await _user(session, mobile=merchant_mobile, name="Test Merchant", role_code="manager", email=_safe_email("merchant.test", merchant_mobile))
        merchant = await session.scalar(select(Merchant).where(Merchant.code == "MBGA-TEST-M001"))
        now = datetime.now(UTC)
        if merchant is not None and merchant.mobile_number in LEGACY_TEST_MOBILES.values():
            merchant.mobile_number = merchant_mobile
            merchant.email = _safe_email("merchant.test", merchant_mobile)
            merchant.updated_at = now
        if merchant is None:
            merchant = Merchant(
                id=str(uuid4()),
                code="MBGA-TEST-M001",
                name="Test Merchant",
                mobile_number=merchant_mobile,
                contact_person_name="Test Merchant",
                email=_safe_email("merchant.test", merchant_mobile),
                gst_number=None,
                address_line_1=TEST_TAG,
                address_line_2=None,
                city="Test City",
                state="Test State",
                postal_code="000000",
                status="ACTIVE",
                approval_status="APPROVED",
                created_by=admin.id,
                created_at=now,
                updated_at=now,
            )
            session.add(merchant)
            await session.flush()
        await _assign(session, merchant_user, "manager", "merchant", merchant.id)
        if not await session.scalar(select(MerchantUser).where(MerchantUser.merchant_id == merchant.id, MerchantUser.user_id == merchant_user.id)):
            session.add(MerchantUser(id=str(uuid4()), merchant_id=merchant.id, user_id=merchant_user.id, staff_type="PRIMARY_MANAGER", status="ACTIVE", notes=TEST_TAG, created_at=now, updated_at=now))

        for mobile, name, role_code, employee_code, user_type in [
            (driver_mobile, "Test Driver", "driver", "MBGA-TEST-DRV-001", "DRIVER"),
            (helper_mobile, "Test Helper", "helper", "MBGA-TEST-HLP-001", "HELPER"),
        ]:
            user = await _user(session, mobile=mobile, name=name, role_code=role_code, email=None)
            await _assign(session, user, role_code, "merchant", merchant.id)
            profile = await session.scalar(select(DeliveryProfile).where(DeliveryProfile.merchant_id == merchant.id, DeliveryProfile.employee_code == employee_code))
            if profile is None:
                session.add(
                    DeliveryProfile(
                        id=str(uuid4()),
                        merchant_id=merchant.id,
                        user_id=user.id,
                        delivery_user_type=user_type,
                        employee_code=employee_code,
                        driving_license_number="TEST-DL-001" if user_type == "DRIVER" else None,
                        driving_license_expiry=datetime.now(UTC) + timedelta(days=365) if user_type == "DRIVER" else None,
                        address=TEST_TAG,
                        status="ACTIVE",
                        approval_status="APPROVED",
                        created_at=now,
                        updated_at=now,
                    )
                )
        await session.commit()
    print("Seeded MBGA account test data. Use configured test mobiles and development OTP.")


if __name__ == "__main__":
    asyncio.run(main())
