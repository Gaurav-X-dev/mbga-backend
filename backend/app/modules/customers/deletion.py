"""Permanent profile deletion, restricted to accounts without business references."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer_access.models import (
    CustomerBrand,
    CustomerMembership,
    CustomerOutlet,
    CustomerTeamMember,
)
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant
from app.shared.business.actor import BusinessActor
from app.shared.business.audit import BusinessAuditor
from app.shared.database.base import Base
from app.shared.exceptions.api_error import ApiError

# Registration/configuration data can go with the profile. Every other reference
# (including new business tables added later) blocks deletion by default.
REMOVABLE = frozenset(
    {
        "customer_delivery_sites",
        "kyc_applications",
        "customer_report_memberships",
        "customer_price_overrides",
    }
)


def referenced_columns():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if any(fk.target_fullname == "customer_profiles.id" for fk in column.foreign_keys):
                yield table, column


async def permanently_delete_customer(
    session: AsyncSession, actor: BusinessActor, customer_id: str
) -> None:
    # Access writers lock the merchant first. Serialize deletion with invitations,
    # branch linking and role changes so no access can be added during cleanup.
    await session.get(Merchant, actor.require_merchant_id(), with_for_update=True)
    profile = await session.scalar(
        select(CustomerProfile)
        .where(
            CustomerProfile.id == customer_id,
            CustomerProfile.merchant_id == actor.require_merchant_id(),
        )
        .with_for_update()
    )
    if profile is None:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    owned_brand = await session.scalar(
        select(CustomerBrand)
        .where(
            CustomerBrand.owner_customer_id == customer_id,
            CustomerBrand.merchant_id == actor.require_merchant_id(),
        )
        .with_for_update()
    )
    if owned_brand is not None and await session.scalar(
        select(CustomerOutlet.customer_id).where(CustomerOutlet.brand_id == owned_brand.id).limit(1)
    ):
        raise ApiError(
            "CUSTOMER_DELETE_OWNER_LINKED",
            409,
            "Unlink this owner's branches before deleting the customer. Branch accounts will be preserved.",
        )
    references = list(referenced_columns())
    for table, column in references:
        if table.name in REMOVABLE or table.name in {"customer_documents", "customer_brands"}:
            continue
        if await session.scalar(select(column).where(column == customer_id).limit(1)):
            if table.name == "customer_brand_outlets":
                raise ApiError(
                    "CUSTOMER_DELETE_OUTLET_LINKED",
                    409,
                    "Unlink this customer from its brand before deleting.",
                )
            raise ApiError(
                "CUSTOMER_DELETE_BLOCKED",
                409,
                "Customer has business records or account links. Remove account links first; customers with transaction history cannot be permanently deleted.",
            )
    try:
        # A savepoint makes concurrent FK violations a clean conflict, never a partial delete.
        async with session.begin_nested():
            # Account deletion terminates its extra-user access; old invitation/audit
            # rows stay as REVOKED evidence and can no longer be accepted.
            await session.execute(
                update(CustomerMembership)
                .where(
                    CustomerMembership.merchant_id == actor.require_merchant_id(),
                    CustomerMembership.scope_type == "OUTLET",
                    CustomerMembership.scope_id == customer_id,
                    CustomerMembership.status != "REVOKED",
                )
                .values(status="REVOKED")
            )
            await session.execute(
                update(CustomerTeamMember)
                .where(
                    (CustomerTeamMember.owner_customer_id == customer_id)
                    | (
                        (CustomerTeamMember.scope_type == "ACCOUNT")
                        & (CustomerTeamMember.scope_id == customer_id)
                    ),
                    CustomerTeamMember.merchant_id == actor.require_merchant_id(),
                    CustomerTeamMember.status == "ACTIVE",
                )
                .values(status="REVOKED", updated_by=actor.user_id, updated_at=datetime.now(UTC))
            )
            if owned_brand is not None:
                await session.execute(
                    update(CustomerMembership)
                    .where(
                        CustomerMembership.merchant_id == actor.require_merchant_id(),
                        CustomerMembership.scope_type == "BRAND",
                        CustomerMembership.scope_id == owned_brand.id,
                        CustomerMembership.status != "REVOKED",
                    )
                    .values(status="REVOKED")
                )
                await session.delete(owned_brand)
                await session.flush()
            for table, column in references:
                if table.name == "customer_documents":
                    # Preserve finalized uploads as evidence; never make them reusable.
                    await session.execute(
                        update(table).where(column == customer_id).values(customer_id=None)
                    )
                elif table.name in REMOVABLE:
                    await session.execute(delete(table).where(column == customer_id))
            await session.delete(profile)
            await session.flush()
            await BusinessAuditor(session).record(
                "CUSTOMER_PERMANENTLY_DELETED",
                actor=actor,
                entity_type="CUSTOMER",
                entity_id=customer_id,
                message="Customer profile deleted; scoped access revoked, empty owner group removed, uploaded evidence and login identity retained.",
            )
    except IntegrityError as exc:
        raise ApiError(
            "CUSTOMER_DELETE_BLOCKED",
            409,
            "Customer has linked records and cannot be permanently deleted.",
        ) from exc
