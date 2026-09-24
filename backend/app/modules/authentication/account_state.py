"""Account state per app channel.

One place decides whether a user may use an app and which screen the app should open next.
It is used by OTP verification, token refresh, every authenticated request and ``/me``.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import CustomerDocument, CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.roles.models import Role, RoleLoginChannel
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.modules.users.role_repository import UserRoleRepository
from app.shared.exceptions.api_error import ApiError


class NextAction(StrEnum):
    COMPLETE_PROFILE = "COMPLETE_PROFILE"
    SUBMIT_DOCUMENTS = "SUBMIT_DOCUMENTS"
    WAIT_FOR_APPROVAL = "WAIT_FOR_APPROVAL"
    SIGN_IN = "SIGN_IN"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"
    OPEN_CUSTOMER_HOME = "OPEN_CUSTOMER_HOME"
    OPEN_DELIVERY_HOME = "OPEN_DELIVERY_HOME"
    OPEN_MERCHANT_HOME = "OPEN_MERCHANT_HOME"
    OPEN_ADMIN_DASHBOARD = "OPEN_ADMIN_DASHBOARD"


HOME_ACTIONS = {
    LoginChannel.ADMIN: NextAction.OPEN_ADMIN_DASHBOARD,
    LoginChannel.MERCHANT: NextAction.OPEN_MERCHANT_HOME,
    LoginChannel.DELIVERY: NextAction.OPEN_DELIVERY_HOME,
    LoginChannel.CUSTOMER: NextAction.OPEN_CUSTOMER_HOME,
}

# Customer profile statuses (see docs/customer-registration.md).
CUSTOMER_PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
CUSTOMER_DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
CUSTOMER_UNDER_REVIEW = "UNDER_REVIEW"
CUSTOMER_APPROVED = "APPROVED"
CUSTOMER_REJECTED = "REJECTED"
CUSTOMER_SUSPENDED = "SUSPENDED"
CUSTOMER_ROLE_CODE = "customer"
# Primary role (the `role` field) is the first match in this order; unknown custom roles come last.
ROLE_PRIORITY = ["super_admin", "manager", "salesperson", "godown_stock_manager", "accountant", "driver", "helper", "customer"]


@dataclass
class AccountState:
    user: User
    channel: LoginChannel
    account_status: str
    approval_status: str | None = None
    profile_completion_status: str | None = None
    next_action: NextAction = NextAction.CONTACT_SUPPORT
    # Set when the user may not use the app with a full session: (code, HTTP status).
    denial: tuple[str, int] | None = None
    # Set when the user may not hold even a restricted onboarding session.
    onboarding_denial: tuple[str, int] | None = None
    role: str | None = None
    active_roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    merchant: dict | None = None
    delivery_profile: dict | None = None
    customer_profile: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.denial is None

    def next_action_for(self, session_type: str) -> NextAction:
        """An onboarding session cannot open the app: approved customers must sign in first."""
        if session_type == "onboarding" and self.next_action in HOME_ACTIONS.values():
            return NextAction.SIGN_IN
        return self.next_action

    def raise_if_denied(self, *, onboarding: bool = False) -> None:
        denial = self.onboarding_denial if onboarding else self.denial
        if denial is not None:
            raise ApiError(denial[0], denial[1])


FORBIDDEN = status.HTTP_403_FORBIDDEN


class AccountStateResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, user: User, channel: LoginChannel) -> AccountState:
        now = datetime.now(UTC)
        permissions = await UserRoleRepository(self.session).get_effective_permissions(user_id=user.id, login_channel=channel, now=now)
        roles = await self.channel_role_codes(user.id, channel, now)
        state = AccountState(
            user=user,
            channel=channel,
            account_status=user.status,
            role=roles[0] if roles else None,
            active_roles=roles,
            permissions=permissions,
        )
        if channel == LoginChannel.CUSTOMER:
            await self._resolve_customer(state)
            return state
        if user.status == "BLOCKED":
            state.denial = ("ACCOUNT_BLOCKED", FORBIDDEN)
        elif user.status != "ACTIVE":
            state.denial = ("ACCOUNT_INACTIVE", FORBIDDEN)
        elif not permissions:
            state.denial = ("ROLE_NOT_ASSIGNED", FORBIDDEN)
        elif channel == LoginChannel.ADMIN and "dashboard.view" not in permissions:
            state.denial = ("PERMISSION_DENIED", FORBIDDEN)
        if channel == LoginChannel.MERCHANT:
            await self._resolve_merchant(state)
        elif channel == LoginChannel.DELIVERY:
            await self._resolve_delivery(state)
        state.onboarding_denial = ("TOKEN_TYPE_NOT_ALLOWED", status.HTTP_401_UNAUTHORIZED)
        state.next_action = HOME_ACTIONS[channel] if state.denial is None else self._denied_action(state.denial[0])
        return state

    async def channel_role_codes(self, user_id: str, channel: LoginChannel, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(RoleLoginChannel, RoleLoginChannel.role_id == Role.id)
            .where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
            .where((UserRole.valid_from.is_(None)) | (UserRole.valid_from <= now))
            .where((UserRole.valid_until.is_(None)) | (UserRole.valid_until > now))
            .where(Role.is_active.is_(True))
            .where(RoleLoginChannel.login_channel == channel.value, RoleLoginChannel.is_allowed.is_(True))
            .distinct()
            .order_by(Role.code)
        )
        codes = list(result.scalars().all())
        return sorted(codes, key=lambda code: (ROLE_PRIORITY.index(code) if code in ROLE_PRIORITY else len(ROLE_PRIORITY), code))

    @staticmethod
    def _denied_action(code: str) -> NextAction:
        if code in {"ACCOUNT_PENDING_APPROVAL", "DOCUMENTS_PENDING_APPROVAL"}:
            return NextAction.WAIT_FOR_APPROVAL
        return NextAction.CONTACT_SUPPORT

    async def _resolve_merchant(self, state: AccountState) -> None:
        result = await self.session.execute(
            select(MerchantUser, Merchant)
            .join(Merchant, Merchant.id == MerchantUser.merchant_id)
            .where(MerchantUser.user_id == state.user.id)
            .order_by((MerchantUser.status == "ACTIVE").desc(), MerchantUser.created_at)
        )
        row = result.first()
        if row is None:
            state.denial = state.denial or ("ROLE_NOT_ASSIGNED", FORBIDDEN)
            return
        link, merchant = row
        state.merchant = _merchant_summary(merchant)
        state.merchant["staff_type"] = link.staff_type
        state.approval_status = merchant.approval_status
        if state.denial is not None:
            return
        state.denial = _merchant_denial(merchant) or _link_denial(link.status)

    async def _resolve_delivery(self, state: AccountState) -> None:
        result = await self.session.execute(
            select(DeliveryProfile, Merchant)
            .join(Merchant, Merchant.id == DeliveryProfile.merchant_id)
            .where(DeliveryProfile.user_id == state.user.id)
            .order_by((DeliveryProfile.status == "ACTIVE").desc(), DeliveryProfile.created_at)
        )
        row = result.first()
        if row is None:
            state.denial = state.denial or ("ROLE_NOT_ASSIGNED", FORBIDDEN)
            return
        profile, merchant = row
        state.merchant = _merchant_summary(merchant)
        state.delivery_profile = {
            "id": profile.id,
            "delivery_user_type": profile.delivery_user_type,
            "employee_code": profile.employee_code,
            "status": profile.status,
            "approval_status": profile.approval_status,
        }
        state.approval_status = profile.approval_status
        if state.denial is not None:
            return
        if profile.approval_status == "REJECTED":
            state.denial = ("ACCOUNT_REJECTED", FORBIDDEN)
        elif profile.approval_status != "APPROVED":
            state.denial = ("ACCOUNT_PENDING_APPROVAL", FORBIDDEN)
        else:
            state.denial = _link_denial(profile.status)
        state.denial = state.denial or _merchant_denial(merchant)

    async def _resolve_customer(self, state: AccountState) -> None:
        user = state.user
        profile = await self.session.scalar(
            select(CustomerProfile).where((CustomerProfile.user_id == user.id) | (CustomerProfile.mobile_number == user.mobile_number))
        )
        if user.status == "BLOCKED":
            state.denial = ("ACCOUNT_BLOCKED", FORBIDDEN)
            state.onboarding_denial = ("ACCOUNT_BLOCKED", FORBIDDEN)
        if profile is None:
            state.profile_completion_status = "NOT_STARTED"
            state.approval_status = "NOT_SUBMITTED"
            state.denial = state.denial or ("ACCOUNT_PENDING_APPROVAL", FORBIDDEN)
            state.next_action = NextAction.CONTACT_SUPPORT if user.status == "BLOCKED" else NextAction.COMPLETE_PROFILE
            return
        state.customer_profile = {
            "id": profile.id,
            "customer_type": profile.customer_type,
            "name": profile.name,
            "merchant_code": profile.merchant_code,
            "status": profile.status,
            "rejection_reason": profile.rejection_reason,
            "submitted_at": profile.submitted_at,
        }
        state.approval_status = _customer_approval_status(profile.status)
        state.profile_completion_status = "COMPLETE" if profile_is_complete(profile) else "INCOMPLETE"
        if state.denial is None:
            state.denial = await self._customer_denial(state, profile)
        state.next_action = self._customer_next_action(state, profile)

    async def _customer_denial(self, state: AccountState, profile: CustomerProfile) -> tuple[str, int] | None:
        """Whether a registered customer may sign in to the Customer app.

        A customer whose application is still being decided **is allowed in**. The app then
        routes on `next_action` and `customer_profile.status`: approved customers reach the
        home screen, everyone else lands on the verification-status screen. This is what
        spec §3.2 describes when it says `customerStatus` drives routing, and it is what lets
        a customer see a rejection reason instead of being turned away with an error they
        cannot act on.

        Suspension is different and still blocks: it is a deliberate administrative action,
        and its screen is "contact support", not "wait".
        """
        if profile.status == CUSTOMER_SUSPENDED:
            return ("ACCOUNT_SUSPENDED", FORBIDDEN)
        if profile.status != CUSTOMER_APPROVED:
            return None
        if state.user.status != "ACTIVE":
            return ("ACCOUNT_INACTIVE", FORBIDDEN)
        if CUSTOMER_ROLE_CODE not in state.active_roles:
            return ("ROLE_NOT_ASSIGNED", FORBIDDEN)
        pending_document = await self.session.scalar(
            select(CustomerDocument.id).where(
                CustomerDocument.customer_id == profile.id,
                CustomerDocument.is_mandatory.is_(True),
                CustomerDocument.status != "APPROVED",
            )
        )
        if pending_document is not None:
            return ("DOCUMENTS_PENDING_APPROVAL", FORBIDDEN)
        return None

    @staticmethod
    def _customer_next_action(state: AccountState, profile: CustomerProfile) -> NextAction:
        if state.user.status == "BLOCKED" or profile.status == CUSTOMER_SUSPENDED:
            return NextAction.CONTACT_SUPPORT
        if profile.status in {CUSTOMER_PROFILE_INCOMPLETE, CUSTOMER_REJECTED}:
            return NextAction.COMPLETE_PROFILE
        if profile.status == CUSTOMER_DOCUMENTS_PENDING:
            return NextAction.SUBMIT_DOCUMENTS
        if profile.status == CUSTOMER_UNDER_REVIEW:
            return NextAction.WAIT_FOR_APPROVAL
        if state.denial is None:
            return NextAction.OPEN_CUSTOMER_HOME
        if state.denial[0] == "DOCUMENTS_PENDING_APPROVAL":
            return NextAction.WAIT_FOR_APPROVAL
        return NextAction.CONTACT_SUPPORT


def profile_is_complete(profile: CustomerProfile) -> bool:
    return bool(profile.name and profile.customer_type and profile.merchant_code)


def _customer_approval_status(profile_status: str) -> str:
    if profile_status in {CUSTOMER_PROFILE_INCOMPLETE, CUSTOMER_DOCUMENTS_PENDING}:
        return "NOT_SUBMITTED"
    if profile_status == CUSTOMER_UNDER_REVIEW:
        return "PENDING"
    return profile_status


def _merchant_summary(merchant: Merchant) -> dict:
    return {
        "id": merchant.id,
        "code": merchant.code,
        "name": merchant.name,
        "status": merchant.status,
        "approval_status": merchant.approval_status,
    }


def _merchant_denial(merchant: Merchant) -> tuple[str, int] | None:
    if merchant.status == "BLOCKED":
        return ("MERCHANT_BLOCKED", FORBIDDEN)
    if merchant.approval_status == "REJECTED":
        return ("ACCOUNT_REJECTED", FORBIDDEN)
    if merchant.approval_status != "APPROVED":
        return ("ACCOUNT_PENDING_APPROVAL", FORBIDDEN)
    if merchant.status != "ACTIVE":
        return ("MERCHANT_INACTIVE", FORBIDDEN)
    return None


def _link_denial(link_status: str) -> tuple[str, int] | None:
    if link_status == "BLOCKED":
        return ("ACCOUNT_BLOCKED", FORBIDDEN)
    if link_status != "ACTIVE":
        return ("ACCOUNT_INACTIVE", FORBIDDEN)
    return None
