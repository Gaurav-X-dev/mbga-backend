"""KYC approval and rejection.

The existing approve/reject routes keep their paths and their shapes; this module is the
hardened decision logic behind them. What it adds over the previous inline version:

* the application row is decided, not just the profile, so the apps get a stable id and the
  history of a resubmission survives;
* approval verifies the *substance* of the application — every mandatory document present,
  finalized, un-rejected, scanned, with a valid number, and an industrial primary site —
  rather than only checking the profile's status;
* both decisions take the row lock before reading it, so two reviewers pressing Approve and
  Reject at the same moment cannot both succeed.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.account_state import (
    CUSTOMER_APPROVED,
    CUSTOMER_REJECTED,
    CUSTOMER_ROLE_CODE,
)
from app.modules.customers.constants import (
    APPLICATION_TRANSITIONS,
    DOCUMENT_APPROVED,
    REQUIRED_DOCUMENTS,
    ApplicationStatus,
    CustomerType,
    DocumentStatus,
    KycStatus,
    ScanStatus,
)
from app.modules.customers.models import (
    CustomerDeliverySite,
    CustomerDocument,
    CustomerProfile,
    KycApplication,
)
from app.modules.customers.registration import ACCOUNT_STATE
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.business.actor import BusinessActor
from app.shared.business.audit import BusinessAuditor
from app.shared.business.transitions import StatusMachine
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications import (
    NotificationOutboxWriter,
    account_approved,
    application_rejected,
)

APPLICATION_STATE = StatusMachine("kyc application", APPLICATION_TRANSITIONS)
MIN_REJECTION_REASON = 10


class KycReviewService:
    """Approves or rejects one application, atomically."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        auditor: BusinessAuditor | None = None,
        allow_skipped_scan: bool = False,
    ) -> None:
        self.session = session
        self.auditor = auditor
        self.allow_skipped_scan = allow_skipped_scan
        self.notifications = NotificationOutboxWriter(session)

    # --- loading ---------------------------------------------------------------------------

    async def locked_profile(self, customer_id: str, actor: BusinessActor) -> CustomerProfile:
        """Load and lock a customer of the actor's merchant, or 404.

        A customer belonging to another merchant is reported as missing, so a reviewer
        cannot discover which customer ids exist outside their own merchant.
        """
        profile = await self.session.scalar(
            select(CustomerProfile).where(CustomerProfile.id == customer_id).with_for_update()
        )
        if profile is None or profile.merchant_id != actor.require_merchant_id():
            raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return profile

    async def locked_application(self, application_id: str, actor: BusinessActor) -> tuple[KycApplication, CustomerProfile]:
        application = await self.session.scalar(
            select(KycApplication).where(KycApplication.id == application_id).with_for_update()
        )
        if application is None or application.merchant_id != actor.require_merchant_id():
            raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        profile = await self.session.scalar(
            select(CustomerProfile).where(CustomerProfile.id == application.customer_id).with_for_update()
        )
        if profile is None:
            raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return application, profile

    async def pending_application(self, profile: CustomerProfile) -> KycApplication:
        application = await self.session.scalar(
            select(KycApplication)
            .where(
                KycApplication.customer_id == profile.id,
                KycApplication.status == ApplicationStatus.PENDING.value,
            )
            .with_for_update()
        )
        if application is None:
            # The profile says under review but no application is open, or the application
            # was already decided by a concurrent request. Either way the move is refused.
            raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT)
        return application

    # --- approval --------------------------------------------------------------------------

    async def approve(self, profile: CustomerProfile, actor: BusinessActor) -> KycApplication:
        application = await self.pending_application(profile)
        ACCOUNT_STATE.require_move(profile.status, CUSTOMER_APPROVED)
        APPLICATION_STATE.require_move(application.status, ApplicationStatus.APPROVED.value)
        documents = await self._documents(profile.id)
        sites = await self._sites(profile.id)
        await self._require_complete_application(profile, documents, sites)

        user = await self.session.get(User, profile.user_id) if profile.user_id else None
        if user is None:
            raise ApiError(
                "INVALID_STATUS_TRANSITION",
                status.HTTP_409_CONFLICT,
                "The applicant has not verified the mobile number.",
            )

        now = datetime.now(UTC)
        profile.status = CUSTOMER_APPROVED
        profile.kyc_status = KycStatus.VERIFIED.value
        profile.rejection_reason = None
        profile.approved_at = now
        profile.reviewed_by = actor.user_id
        profile.reviewed_at = now
        profile.updated_at = now
        for document in documents:
            if document.status != DocumentStatus.REJECTED.value:
                document.status = DOCUMENT_APPROVED
                document.reviewed_by = actor.user_id
                document.reviewed_at = now
                document.updated_at = now
        application.status = ApplicationStatus.APPROVED.value
        application.reviewed_at = now
        application.reviewed_by_user_id = actor.user_id
        application.reviewed_by_name = actor.display_name
        application.updated_at = now
        if user.status == "PENDING":
            user.status = "ACTIVE"
            user.updated_at = now
        await self._ensure_customer_role(user.id, profile.merchant_id, actor.user_id, now)
        self.notifications.queue(account_approved(profile.id, profile.name or "your business", application.id))
        if self.auditor:
            await self.auditor.record(
                "customer.approved",
                actor=actor,
                entity_type="customer_profile",
                entity_id=profile.id,
                message="Customer registration approved",
            )
        return application

    async def _require_complete_application(
        self,
        profile: CustomerProfile,
        documents: list[CustomerDocument],
        sites: list[CustomerDeliverySite],
    ) -> None:
        """Refuse an approval the customer record cannot actually support.

        Each check corresponds to something that would otherwise be discovered much later —
        an approved customer with no PAN on file, or an industrial customer with nowhere to
        deliver to.
        """
        missing = [
            field
            for field in ("name", "owner_name", "customer_type", "address_line1", "address_city", "address_pincode")
            if not getattr(profile, field)
        ]
        if missing:
            raise ApiError(
                "REGISTRATION_INCOMPLETE",
                status.HTTP_409_CONFLICT,
                "The customer profile is incomplete.",
            )
        customer_type = CustomerType(profile.customer_type)
        by_type = {document.document_type: document for document in documents}
        for required in REQUIRED_DOCUMENTS[customer_type]:
            document = by_type.get(required.value)
            if document is None or document.finalized_at is None:
                raise ApiError(
                    "DOCUMENTS_PENDING_APPROVAL",
                    status.HTTP_409_CONFLICT,
                    f"The {required.value} document is missing.",
                )
            if document.status == DocumentStatus.REJECTED.value:
                raise ApiError(
                    "DOCUMENTS_PENDING_APPROVAL",
                    status.HTTP_409_CONFLICT,
                    f"The {required.value} document was rejected.",
                )
            if not self._scan_is_approvable(document.scan_status):
                raise ApiError(
                    "DOCUMENT_SCAN_PENDING",
                    status.HTTP_409_CONFLICT,
                    f"The {required.value} document has not passed the security scan.",
                )
            if not document.number_masked or not document.number_encrypted:
                raise ApiError(
                    "DOCUMENTS_PENDING_APPROVAL",
                    status.HTTP_409_CONFLICT,
                    f"The {required.value} number is missing.",
                )
        if customer_type is CustomerType.INDUSTRIAL:
            primaries = [site for site in sites if site.is_primary and site.is_active]
            if len(primaries) != 1:
                raise ApiError(
                    "REGISTRATION_INCOMPLETE",
                    status.HTTP_409_CONFLICT,
                    "The customer must have exactly one primary delivery site.",
                )


    def _scan_is_approvable(self, value: str | None) -> bool:
        try:
            scan_status = ScanStatus(value)
        except ValueError:
            return False
        if scan_status is ScanStatus.CLEAN:
            return True
        return self.allow_skipped_scan and scan_status is ScanStatus.SKIPPED

    # --- rejection -------------------------------------------------------------------------

    async def reject(self, profile: CustomerProfile, actor: BusinessActor, reason: str) -> KycApplication:
        cleaned = (reason or "").strip()
        if len(cleaned) < MIN_REJECTION_REASON:
            raise ApiError(
                "REJECTION_REASON_REQUIRED",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[
                    {
                        "field": "rejectionReason",
                        "code": "too_short",
                        "message": f"Give a reason of at least {MIN_REJECTION_REASON} characters.",
                    }
                ],
            )
        application = await self.pending_application(profile)
        ACCOUNT_STATE.require_move(profile.status, CUSTOMER_REJECTED)
        APPLICATION_STATE.require_move(application.status, ApplicationStatus.REJECTED.value)

        now = datetime.now(UTC)
        profile.status = CUSTOMER_REJECTED
        profile.kyc_status = KycStatus.REJECTED.value
        profile.rejection_reason = cleaned
        profile.reviewed_by = actor.user_id
        profile.reviewed_at = now
        profile.updated_at = now
        application.status = ApplicationStatus.REJECTED.value
        application.rejection_reason = cleaned
        application.reviewed_at = now
        application.reviewed_by_user_id = actor.user_id
        application.reviewed_by_name = actor.display_name
        application.updated_at = now
        self.notifications.queue(application_rejected(profile.id, profile.name or "your business", cleaned, application.id))
        if self.auditor:
            await self.auditor.record(
                "customer.rejected",
                actor=actor,
                entity_type="customer_profile",
                entity_id=profile.id,
                # The reason is stored on the row; it is not repeated into the audit message,
                # which is read by a wider audience than the customer record is.
                message="Customer registration rejected",
            )
        return application

    # --- helpers ---------------------------------------------------------------------------

    async def _documents(self, customer_id: str) -> list[CustomerDocument]:
        return list(
            await self.session.scalars(select(CustomerDocument).where(CustomerDocument.customer_id == customer_id))
        )

    async def _sites(self, customer_id: str) -> list[CustomerDeliverySite]:
        return list(
            await self.session.scalars(
                select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == customer_id)
            )
        )

    async def _ensure_customer_role(self, user_id: str, merchant_id: str | None, actor_user_id: str, now: datetime) -> None:
        """Grant the customer role, scoped to the merchant. Never any other role."""
        role = await self.session.scalar(select(Role).where(Role.code == CUSTOMER_ROLE_CODE, Role.is_active.is_(True)))
        if role is None:
            raise ApiError("INTERNAL_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR, "The customer role is not configured.")
        existing = await self.session.scalar(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
                UserRole.scope_type == "merchant",
                UserRole.scope_id == merchant_id,
            )
        )
        if existing is not None:
            existing.is_active = True
            existing.valid_until = None
            return
        self.session.add(
            UserRole(
                id=str(uuid4()),
                user_id=user_id,
                role_id=role.id,
                assigned_at=now,
                assigned_by=actor_user_id,
                valid_from=None,
                valid_until=None,
                is_active=True,
                scope_type="merchant",
                scope_id=merchant_id,
            )
        )
