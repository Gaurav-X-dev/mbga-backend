"""The authenticated actor as business code sees it.

This is a *business-layer adapter* over `app.shared.authorization.context.AuthContext`. The
authentication contract is frozen, so nothing here changes how a session is validated: the
auth dependency resolves the session, and this module answers the extra questions business
services ask — which merchant, which customer profile, what display name.

Actor identity is never read from a request body. `created_by`, `collected_by`,
`recorded_by`, `reviewed_by` and `entered_by` all come from `BusinessActor.display_name`
(spec §1, "Actor fields").
"""

from dataclasses import dataclass

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.users.models import User
from app.shared.authorization.context import AuthContext
from app.shared.exceptions.api_error import ApiError


@dataclass(frozen=True)
class BusinessActor:
    """Who is acting, and the tenancy they are confined to."""

    user_id: str
    login_channel: LoginChannel
    display_name: str
    session_id: str | None = None
    # Set for merchant-channel actors; every merchant query is filtered by it.
    merchant_id: str | None = None
    merchant_code: str | None = None
    staff_type: str | None = None
    # Set for customer-channel actors who have a profile.
    customer_id: str | None = None

    @property
    def is_merchant_staff(self) -> bool:
        return self.login_channel == LoginChannel.MERCHANT and self.merchant_id is not None

    @property
    def is_customer(self) -> bool:
        return self.login_channel == LoginChannel.CUSTOMER

    def require_merchant_id(self) -> str:
        """The merchant every query must be scoped to, or 403."""
        if self.merchant_id is None:
            raise ApiError("ROLE_NOT_ASSIGNED", status.HTTP_403_FORBIDDEN)
        return self.merchant_id

    def require_customer_id(self) -> str:
        """The customer profile the actor owns, or 403."""
        if self.customer_id is None:
            raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_403_FORBIDDEN)
        return self.customer_id


class BusinessActorResolver:
    """Builds a `BusinessActor` from an already-validated `AuthContext`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, context: AuthContext) -> BusinessActor:
        user = await self.session.get(User, context.user_id)
        if user is None:
            # The session validated but the account is gone; treat as signed out.
            raise ApiError("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        # Customers may hold a session while their application is still pending - the auth
        # layer decides that, and re-deciding it here would lock them out of the very screen
        # that shows them their status. Staff channels stay strict.
        if user.status != "ACTIVE" and context.login_channel != LoginChannel.CUSTOMER:
            raise ApiError("ACCOUNT_INACTIVE", status.HTTP_403_FORBIDDEN)
        if user.status == "BLOCKED":
            raise ApiError("ACCOUNT_BLOCKED", status.HTTP_403_FORBIDDEN)

        actor = BusinessActor(
            user_id=user.id,
            login_channel=context.login_channel,
            display_name=_display_name(user),
            session_id=context.session_id,
        )
        if context.login_channel == LoginChannel.MERCHANT:
            return await self._with_merchant(actor, user.id)
        if context.login_channel == LoginChannel.CUSTOMER:
            return await self._with_customer(actor, user)
        return actor

    async def resolve_viewer(self, user_id: str, channel: LoginChannel) -> BusinessActor:
        """Rebuild an actor from a user id alone, for a signed document link.

        A signed link carries its viewer instead of an Authorization header, so there is no
        session to resolve.

        This does **not** require an ACTIVE account, and that is deliberate: a customer still
        in onboarding is PENDING by design, and they must be able to see the document they
        just uploaded. What it does still enforce is the check that matters for a link that
        outlives the request that minted it — a merchant viewer must still have a live link
        to their merchant, so a reviewer removed from the business loses the file at once
        rather than when the link expires. The caller then runs the ownership check on top.
        """
        user = await self.session.get(User, user_id)
        if user is None:
            raise ApiError("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        if user.status == "BLOCKED":
            raise ApiError("ACCOUNT_BLOCKED", status.HTTP_403_FORBIDDEN)

        actor = BusinessActor(
            user_id=user.id,
            login_channel=channel,
            display_name=_display_name(user),
            session_id=None,
        )
        if channel == LoginChannel.MERCHANT:
            return await self._with_merchant(actor, user.id)
        return await self._with_customer(actor, user)

    async def _with_merchant(self, actor: BusinessActor, user_id: str) -> BusinessActor:
        row = (
            await self.session.execute(
                select(MerchantUser, Merchant)
                .join(Merchant, Merchant.id == MerchantUser.merchant_id)
                .where(MerchantUser.user_id == user_id)
                .order_by((MerchantUser.status == "ACTIVE").desc(), MerchantUser.created_at)
            )
        ).first()
        if row is None:
            raise ApiError("ROLE_NOT_ASSIGNED", status.HTTP_403_FORBIDDEN)
        link, merchant = row
        if link.status != "ACTIVE":
            raise ApiError("ACCOUNT_INACTIVE", status.HTTP_403_FORBIDDEN)
        if merchant.status == "BLOCKED":
            raise ApiError("MERCHANT_BLOCKED", status.HTTP_403_FORBIDDEN)
        if merchant.status != "ACTIVE":
            raise ApiError("MERCHANT_INACTIVE", status.HTTP_403_FORBIDDEN)
        return BusinessActor(
            **{
                **actor.__dict__,
                "merchant_id": merchant.id,
                "merchant_code": merchant.code,
                "staff_type": link.staff_type,
            }
        )

    async def _with_customer(self, actor: BusinessActor, user: User) -> BusinessActor:
        # A customer may be signed in before a profile exists (accountStatus NEW), so a
        # missing profile is not an error here — require_customer_id() decides that.
        profile = await self.session.scalar(
            select(CustomerProfile).where(
                (CustomerProfile.user_id == user.id) | (CustomerProfile.mobile_number == user.mobile_number)
            )
        )
        if profile is None:
            return actor
        return BusinessActor(
            **{
                **actor.__dict__,
                "customer_id": profile.id,
                "merchant_id": profile.merchant_id,
                "merchant_code": profile.merchant_code,
            }
        )


def _display_name(user: User) -> str:
    """The name written into actor fields. Never the mobile number."""
    return user.full_name or user.username or "Unknown user"
