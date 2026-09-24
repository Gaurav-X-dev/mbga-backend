"""Turning "who is this for" into "which devices does that mean".

A queued event names an audience, not a phone: `customer/<customer id>` or
`merchant/<merchant id>`. This resolves that to the live push tokens to send to.

Tokens live on `login_sessions.push_token`, written when a session is created and cleared
when it is revoked, so "a live session" and "a device worth notifying" are the same thing -
a signed-out phone drops out of here automatically rather than needing its own cleanup.
"""

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.models import LoginSession
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import MerchantUser
from app.modules.notifications.constants import RecipientKind


@dataclass(frozen=True)
class Device:
    """One phone to notify."""

    user_id: str
    token: str


class RecipientResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def devices_for(self, recipient_kind: str, recipient_id: str) -> list[Device]:
        """Every live device that should receive this event."""
        user_ids = await self._user_ids(recipient_kind, recipient_id)
        if not user_ids:
            return []
        rows = await self.session.execute(
            select(LoginSession.user_id, LoginSession.push_token)
            .where(
                LoginSession.user_id.in_(user_ids),
                LoginSession.push_token.is_not(None),
                LoginSession.push_token != "",
                LoginSession.revoked_at.is_(None),
            )
        )
        # One device can hold several live sessions (a refresh leaves the old row behind for
        # a while); sending twice to the same token would show the user two notifications.
        seen: dict[str, Device] = {}
        for user_id, token in rows:
            seen.setdefault(token, Device(user_id=user_id, token=token))
        return list(seen.values())

    async def _user_ids(self, recipient_kind: str, recipient_id: str) -> list[str]:
        kind = (recipient_kind or "").lower()
        if kind == RecipientKind.USER.value:
            return [recipient_id]
        if kind == RecipientKind.CUSTOMER.value:
            # A customer profile is one person; their user row is what holds sessions.
            user_id = await self.session.scalar(
                select(CustomerProfile.user_id).where(CustomerProfile.id == recipient_id)
            )
            return [user_id] if user_id else []
        if kind == RecipientKind.MERCHANT.value:
            # Spec §15: all staff share the merchant bucket, so every active staff member
            # is notified. A blocked or removed member has no ACTIVE link and drops out.
            return list(
                await self.session.scalars(
                    select(MerchantUser.user_id).where(
                        MerchantUser.merchant_id == recipient_id,
                        MerchantUser.status == "ACTIVE",
                    )
                )
            )
        return []

    async def forget(self, token: str) -> None:
        """Clear a token FCM has told us is dead.

        Cleared rather than the session revoked: the person is still signed in, it is the
        push registration that has gone - reinstalling the app gives them a new token on
        the next sign-in without having been logged out here.
        """
        await self.session.execute(
            update(LoginSession).where(LoginSession.push_token == token).values(push_token=None)
        )
