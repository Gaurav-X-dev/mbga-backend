"""Create a normal customer and attach it to its owner in one transaction."""

from uuid import uuid4

from sqlalchemy import select

from app.modules.authentication.account_state import CUSTOMER_APPROVED
from app.modules.authentication.constants import LoginChannel
from app.modules.customer_access.models import CustomerBrand, CustomerOutlet
from app.modules.customer_access.service import audit
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant
from app.shared.exceptions.api_error import ApiError


async def create_branch(session, actor, owner_id, payload, registration):
    owner = await require_owner(session, actor, owner_id)
    merchant_id = owner.merchant_id
    merchant = await session.get(Merchant, merchant_id)
    brand = await session.scalar(
        select(CustomerBrand).where(
            CustomerBrand.owner_customer_id == owner_id,
            CustomerBrand.merchant_id == merchant_id,
        )
    )
    if brand is None:
        brand = CustomerBrand(
            id=str(uuid4()),
            merchant_id=merchant_id,
            name=owner.name or owner.owner_name or "Customer branches",
            owner_customer_id=owner_id,
        )
        session.add(brand)
        await session.flush()
    sibling_ids = tuple(
        await session.scalars(
            select(CustomerOutlet.customer_id).where(
                CustomerOutlet.brand_id == brand.id,
            )
        )
    )
    profile, _application = await registration.create_customer_by_merchant(
        payload,
        actor,
        merchant,
        shared_customer_ids=(owner.id, *sibling_ids),
    )
    session.add(CustomerOutlet(customer_id=profile.id, brand_id=brand.id))
    audit(session, actor, profile.id, "Created branch for owner " + owner_id)
    await session.flush()
    return profile


async def require_owner(session, actor, owner_id):
    """Only the primary owner can manage its direct children; staff remain tenant-scoped."""
    merchant_id = actor.require_merchant_id()
    await session.get(Merchant, merchant_id, with_for_update=True)
    owner = await session.scalar(
        select(CustomerProfile)
        .where(
            CustomerProfile.id == owner_id,
            CustomerProfile.merchant_id == merchant_id,
        )
        .with_for_update()
    )
    if owner is None:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    if await session.get(CustomerOutlet, owner.id):
        raise ApiError(
            "BRANCH_CANNOT_MANAGE_BRANCHES", 403, "Child branches cannot create or manage branches."
        )
    if actor.login_channel == LoginChannel.CUSTOMER and (
        owner.user_id != actor.user_id or owner.status != CUSTOMER_APPROVED
    ):
        raise ApiError("PERMISSION_DENIED", 403)
    return owner


async def owned_branch(session, actor, owner_id, branch_id):
    await require_owner(session, actor, owner_id)
    row = (
        await session.execute(
            select(CustomerProfile, CustomerOutlet)
            .join(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
            .join(CustomerBrand, CustomerBrand.id == CustomerOutlet.brand_id)
            .where(
                CustomerProfile.id == branch_id,
                CustomerBrand.owner_customer_id == owner_id,
                CustomerBrand.merchant_id == actor.require_merchant_id(),
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    return row


async def change_branch_mobile(session, actor, branch, mobile):
    """Rebind only this branch; never change a shared user's phone or other app roles."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from app.modules.authentication.models import LoginSession
    from app.modules.customers.review import KycReviewService
    from app.modules.customers.validators import FieldErrors, validate_mobile
    from app.modules.users.identity import get_or_create_mobile_user

    errors = FieldErrors()
    number = validate_mobile(mobile, errors)
    errors.raise_if_any()
    if number == branch.mobile_number:
        return
    if await session.scalar(
        select(CustomerProfile.id).where(
            CustomerProfile.mobile_number == number, CustomerProfile.id != branch.id
        )
    ):
        raise ApiError("REGISTRATION_PROFILE_EXISTS", 409)
    old_user_id = branch.user_id
    user, _ = await get_or_create_mobile_user(
        session,
        mobile=number,
        full_name=branch.owner_name,
        legacy_role="customer",
        new_user_status="ACTIVE" if branch.status == CUSTOMER_APPROVED else "PENDING",
    )
    if user.status not in {"ACTIVE", "PENDING"}:
        raise ApiError("ACCOUNT_INACTIVE", 409)
    now = datetime.now(UTC)
    if branch.status == CUSTOMER_APPROVED:
        user.status = "ACTIVE"
        await KycReviewService(session)._ensure_customer_role(
            user.id, branch.merchant_id, actor.user_id, now
        )
    branch.mobile_number = number
    branch.user_id = user.id
    branch.mobile_verified_at = None  # The new holder must still prove the number by OTP.
    if old_user_id and old_user_id != user.id:
        await session.execute(
            update(LoginSession)
            .where(
                LoginSession.user_id == old_user_id,
                LoginSession.login_channel == "CUSTOMER",
                LoginSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason="BRANCH_CONTACT_CHANGED", push_token=None)
        )


async def update_branch(session, actor, owner_id, branch_id, payload, registration=None):
    import json

    from app.modules.customers.editing import CustomerEditRequest, edit_customer

    branch, link = await owned_branch(session, actor, owner_id, branch_id)
    if "mobile" in payload.model_fields_set:
        await change_branch_mobile(session, actor, branch, payload.mobile)
    if "permissions" in payload.model_fields_set:
        link.permissions = json.dumps(payload.permissions)
    # The existing edit service also applies validation, type conversion and its audit.
    await session.flush()
    fields = payload.model_dump(
        by_alias=True, exclude_unset=True, exclude={"mobile", "permissions"}
    )
    if len(fields) == 1:  # Permissions/phone-only edit still stamps the profile and audit.
        fields["businessName"] = branch.name or branch.owner_name or "Branch"
    result = await edit_customer(
        session,
        actor,
        branch_id,
        CustomerEditRequest.model_validate(fields),
        commit=False,
        registration=registration,
    )
    audit(session, actor, branch_id, "Updated owner branch: " + payload.reason)
    return result


async def delete_branch(session, actor, owner_id, branch_id):
    from app.modules.customers.deletion import permanently_delete_customer

    branch, link = await owned_branch(session, actor, owner_id, branch_id)
    # Unlink and delete in one transaction. A transaction-history refusal rolls both back.
    await session.delete(link)
    await session.flush()
    await permanently_delete_customer(session, actor, branch.id)
    audit(session, actor, branch.id, "Deleted branch of owner " + owner_id)
