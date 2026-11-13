"""No balance transfers: delegation only selects an authorized existing customer."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant
from app.modules.users.models import User
from app.shared.exceptions.api_error import ApiError

from .models import CustomerBrand, CustomerOutlet

PERMISSIONS = (
    "profile.view",
    "orders.view",
    "orders.create",
    "orders.cancel",
    "accounts.view",
    "accounts.pay",
    "inventory.view",
    "notifications.view",
)


def audit(session, actor, target, message):
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="CUSTOMER_ACCESS_UPDATED",
            actor_user_id=actor.user_id,
            entity_type="customer_access",
            entity_id=target,
            message=message[:255],
            created_at=datetime.now(UTC),
        )
    )


async def permissions_for_many(session, user_id, customers):
    user = await session.get(User, user_id)
    if not user or user.status not in {"ACTIVE", "PENDING"}:
        raise ApiError("PERMISSION_DENIED", 403)
    links = list(
        await session.scalars(
            select(CustomerOutlet).where(CustomerOutlet.customer_id.in_([c.id for c in customers]))
        )
    )
    by_customer = {link.customer_id: link for link in links}
    owned_brands = set(
        (
            await session.execute(
                select(CustomerBrand.id, CustomerBrand.merchant_id)
                .join(CustomerProfile, CustomerProfile.id == CustomerBrand.owner_customer_id)
                .where(CustomerProfile.user_id == user_id, CustomerProfile.status == "APPROVED")
            )
        ).all()
    )
    from .team import active_team_rows

    team_rows = await active_team_rows(session, user_id)
    brand_owners = (
        dict(
            (
                await session.execute(
                    select(CustomerBrand.id, CustomerBrand.owner_customer_id).where(
                        CustomerBrand.id.in_([link.brand_id for link in links])
                    )
                )
            ).all()
        )
        if links
        else {}
    )
    result = {}
    for customer in customers:
        link = by_customer.get(customer.id)
        if link and (link.brand_id, customer.merchant_id) in owned_brands:
            result[customer.id] = set(PERMISSIONS)
        elif customer.user_id == user_id or (
            user.mobile_number and customer.mobile_number == user.mobile_number
        ):
            result[customer.id] = (
                set(json.loads(link.permissions))
                if link and link.permissions is not None
                else set(PERMISSIONS)
            )
        else:
            result[customer.id] = set()
    for customer in customers:
        link = by_customer.get(customer.id)
        owner_id = brand_owners.get(link.brand_id) if link else customer.id
        result[customer.id] |= {
            permission
            for member in team_rows
            if member.merchant_id == customer.merchant_id
            and member.owner_customer_id == owner_id
            and (member.scope_type == "ALL" or member.scope_id == customer.id)
            for permission in json.loads(member.permissions)
        }
    return result


async def permissions_for(session, user_id, customer):
    return (await permissions_for_many(session, user_id, [customer]))[customer.id]


async def delegated_actor(session, actor, request):
    selected = request.headers.get("X-Customer-Account-Id")
    primary_branch = False
    if not selected and actor.customer_id is None:
        path = request.url.path.split("/customer/", 1)[-1]
        if path.split("/", 1)[0] != "customer-access":
            raise ApiError(
                "CUSTOMER_ACCOUNT_REQUIRED", 422, "Select the customer account you want to use."
            )
    if not selected:
        if not actor.customer_id or not await session.get(CustomerOutlet, actor.customer_id):
            return actor
        selected = actor.customer_id
        primary_branch = True
    if len(selected) > 36:
        raise ApiError("PERMISSION_DENIED", 403)
    customer = await session.get(CustomerProfile, selected)
    if customer is None:
        raise ApiError("PERMISSION_DENIED", 403)
    permissions = await permissions_for(session, actor.user_id, customer)
    path = request.url.path.split("/customer/", 1)[-1]
    root = path.split("/", 1)[0]
    read = request.method in {"GET", "HEAD"}
    if root == "customer-access" or (primary_branch and root in {"registration", "documents"}):
        return actor  # Branch management checks the actual owner identity in its service.
    required = {
        "profile": "profile.view",
        "orders": "orders.view",
        "payments": "accounts.view",
        "invoices": "accounts.view",
        "finance": "accounts.view",
        "inventory": "inventory.view",
        "notifications": "notifications.view",
        "customer-access": "profile.view",
    }.get(root)
    if root == "customers" and read and path.endswith("/payments/summary"):
        required = "accounts.view"
    if root == "orders" and not read:
        required = "orders.cancel" if "cancel" in path.split("/") else "orders.create"
    if not read and root in {"payments", "finance"}:
        required = "accounts.pay"
    notification_read_update = (
        root == "notifications"
        and request.method in {"POST", "PATCH"}
        and (path == "notifications/read-all" or path.endswith("/read"))
    )
    if (
        not read
        and not notification_read_update
        and root not in {"orders", "customer-access", "payments", "finance"}
    ):
        # No delegated KYC/document changes, credit changes, or unreviewed payment mutations.
        raise ApiError(
            "PERMISSION_DENIED", 403, "This operation is not available for delegated accounts."
        )
    if required is None or required not in permissions:
        raise ApiError("PERMISSION_DENIED", 403)
    merchant = await session.get(Merchant, customer.merchant_id)
    if (
        not merchant
        or merchant.status != "ACTIVE"
        or (customer.status != "APPROVED" and root != "profile")
    ):
        raise ApiError("ACCOUNT_INACTIVE", 403)
    return replace(
        actor,
        customer_id=customer.id,
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        delegated=True,
        delegated_permissions=tuple(sorted(permissions)),
    )
