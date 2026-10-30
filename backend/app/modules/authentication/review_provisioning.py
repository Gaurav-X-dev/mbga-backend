"""Idempotent dedicated Play review tenant; never adopts existing real users."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RoleLoginChannel, RolePermission
from app.modules.users.models import User
from app.modules.users.role_models import UserRole


def review_id(name):
    return str(uuid5(NAMESPACE_URL, "mbga://play-review/" + name))


TENANT_ID = review_id("merchant")
TENANT_CODE = "MBGA-PLAY-REVIEW"
MERCHANT_ROLE_CODE = "play_review_merchant"
MERCHANT_MODULES = (
    "dashboard.",
    "customers.",
    "customer_documents.",
    "orders.",
    "pricing.",
    "inventory.",
    "payments.",
    "delivery.",
    "delivery_users.",
    "vehicles.",
    "expenses.",
    "tasks.",
    "reports.",
    "credit.",
)


async def provision_review_accounts(session, settings):
    specs = [
        (
            "customer",
            settings.play_review_customer_mobile,
            "CUSTOMER",
            "customer",
            "Play Review Customer",
        ),
        (
            "merchant-user",
            settings.play_review_merchant_mobile,
            "MERCHANT",
            MERCHANT_ROLE_CODE,
            "Play Review Merchant",
        ),
        ("rider", settings.play_review_delivery_mobile, "DELIVERY", "driver", "Play Review Rider"),
    ]
    phones = [item[1] for item in specs]
    if any(not phone for phone in phones) or len(set(phones)) != 3:
        raise ValueError("Configure three distinct review mobile numbers before provisioning")
    # Check all collisions before adding anything; a real account is never switched to a
    # public fixed OTP merely because its number appears in deployment configuration.
    tenant = await session.get(Merchant, TENANT_ID)
    found = await session.scalar(select(Merchant).where(Merchant.code == TENANT_CODE))
    if (tenant and tenant.code != TENANT_CODE) or (found and found.id != TENANT_ID):
        raise ValueError("Review tenant identifier is already used by another merchant")
    for key, phone, _, role, _ in specs:
        uid = review_id(key)
        user = await session.get(User, uid)
        found_user = await session.scalar(select(User).where(User.mobile_number == phone))
        if user and (user.mobile_number != phone or user.username != "play_review_" + key):
            raise ValueError("Review identity does not match its configured phone")
        if found_user and found_user.id != uid:
            raise ValueError("A review phone is already assigned to another user")
        username_owner = await session.scalar(
            select(User.id).where(User.username == "play_review_" + key)
        )
        if username_owner and username_owner != uid:
            raise ValueError("Review username is already assigned to another user")
        profile = await session.scalar(
            select(CustomerProfile).where(CustomerProfile.mobile_number == phone)
        )
        if profile and (
            key != "customer"
            or profile.id != review_id("customer-profile")
            or profile.user_id != uid
            or profile.merchant_id != TENANT_ID
        ):
            raise ValueError("A review phone is already linked to another customer profile")
    for role_code in ("customer", "driver", "manager"):
        if not await session.scalar(
            select(Role.id).where(Role.code == role_code, Role.is_active.is_(True))
        ):
            raise ValueError("Required seeded role is missing: " + role_code)
    merchant_role = await session.scalar(select(Role).where(Role.code == MERCHANT_ROLE_CODE))
    if merchant_role and merchant_role.id != review_id("merchant-role"):
        raise ValueError("Review role code is already used by another role")
    now = datetime.now(UTC)
    if tenant is None:
        session.add(
            Merchant(
                id=TENANT_ID,
                code=TENANT_CODE,
                name="MBGA Play Review (Demo)",
                status="ACTIVE",
                approval_status="APPROVED",
                city="Pune",
                state="Maharashtra",
                postal_code="411001",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
    if merchant_role is None:
        merchant_role = Role(
            id=review_id("merchant-role"),
            code=MERCHANT_ROLE_CODE,
            name="Play Review Merchant",
            description="Merchant-channel review access within the isolated demo tenant only.",
            role_type="custom",
            is_system=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(merchant_role)
        await session.flush()
        session.add(
            RoleLoginChannel(
                role_id=merchant_role.id, login_channel="MERCHANT", is_allowed=True, created_at=now
            )
        )
        for permission in (
            await session.scalars(select(Permission).where(Permission.is_active.is_(True)))
        ).all():
            if permission.code.startswith(MERCHANT_MODULES):
                session.add(
                    RolePermission(
                        role_id=merchant_role.id, permission_id=permission.id, granted_at=now
                    )
                )
        await session.flush()
    for key, phone, _, role_code, name in specs:
        uid = review_id(key)
        if await session.get(User, uid) is None:
            session.add(
                User(
                    id=uid,
                    username="play_review_" + key,
                    full_name=name,
                    mobile_number=phone,
                    country_code="+91",
                    role="manager" if key == "merchant-user" else role_code,
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
        role_id = await session.scalar(select(Role.id).where(Role.code == role_code))
        link_id = review_id(key + "-role")
        if await session.get(UserRole, link_id) is None:
            session.add(
                UserRole(
                    id=link_id,
                    user_id=uid,
                    role_id=role_id,
                    assigned_at=now,
                    is_active=True,
                    scope_type="merchant",
                    scope_id=TENANT_ID,
                )
            )
    # Keep the standard manager primary-role value expected by existing merchant apps;
    # the additional review role supplies merchant-scoped feature permissions only.
    manager_link_id = review_id("merchant-manager-role")
    if await session.get(UserRole, manager_link_id) is None:
        manager_role_id = await session.scalar(select(Role.id).where(Role.code == "manager"))
        session.add(
            UserRole(
                id=manager_link_id,
                user_id=review_id("merchant-user"),
                role_id=manager_role_id,
                assigned_at=now,
                is_active=True,
                scope_type="merchant",
                scope_id=TENANT_ID,
            )
        )
    if await session.get(MerchantUser, review_id("merchant-link")) is None:
        session.add(
            MerchantUser(
                id=review_id("merchant-link"),
                merchant_id=TENANT_ID,
                user_id=review_id("merchant-user"),
                staff_type="MANAGER",
                status="ACTIVE",
                notes="Dedicated Play Store demo account; no production merchant membership.",
                created_at=now,
                updated_at=now,
            )
        )
    if await session.get(CustomerProfile, review_id("customer-profile")) is None:
        session.add(
            CustomerProfile(
                id=review_id("customer-profile"),
                user_id=review_id("customer"),
                merchant_id=TENANT_ID,
                merchant_code=TENANT_CODE,
                code="PLAY-CUSTOMER-001",
                customer_type="RETAIL",
                mobile_number=settings.play_review_customer_mobile,
                name="Play Review Customer",
                owner_name="Review Account",
                status="APPROVED",
                kyc_status="VERIFIED",
                approved_at=now,
                registered_at=now,
                mobile_verified_at=now,
                address_line1="Demonstration address — Play review only",
                address_city="Pune",
                address_state="Maharashtra",
                address_pincode="411001",
                created_at=now,
                updated_at=now,
            )
        )
    if await session.get(DeliveryProfile, review_id("rider-profile")) is None:
        session.add(
            DeliveryProfile(
                id=review_id("rider-profile"),
                merchant_id=TENANT_ID,
                user_id=review_id("rider"),
                delivery_user_type="DRIVER",
                employee_code="PLAY-RIDER-001",
                status="ACTIVE",
                approval_status="APPROVED",
                on_duty=False,
                created_at=now,
                updated_at=now,
            )
        )
    await session.flush()
    await session.commit()
    return {channel: phone for _, phone, channel, _, _ in specs}
