"""The shared customer-registration domain.

Two actors register customers — the customer themselves, and merchant staff — and almost
everything about the two is identical: the same validation, the same document rules, the same
code allocation, the same profile and application rows, the same audit and notification
events. Only three things genuinely differ, and they are exactly the things that must not be
taken from the request body:

* where the verified mobile number comes from,
* which merchant the customer belongs to,
* whether a customer login identity has to be created.

So there is one set of primitives and two thin commands over them — `register_customer_self`
and `create_customer_by_merchant`. There is deliberately **no** single generic method taking
an actor or an owner id as an argument: that method would be one forgotten check away from
letting a caller register a customer under somebody else's merchant.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.account_state import (
    CUSTOMER_PROFILE_INCOMPLETE,
    CUSTOMER_UNDER_REVIEW,
)
from app.modules.customers.business_schemas import (
    CustomerRegistrationRequest,
    DocumentSubmission,
    SiteSubmission,
)
from app.modules.customers.codes import CustomerCodeAllocator
from app.modules.customers.constants import (
    ACCOUNT_TRANSITIONS,
    EDITABLE_ACCOUNT_STATUSES,
    REQUIRED_DOCUMENTS,
    ApplicationStatus,
    CustomerType,
    DocumentStatus,
    KycDocumentType,
    KycStatus,
    PricingTier,
)
from app.modules.customers.documents import DocumentAccessService
from app.modules.customers.models import (
    CustomerDeliverySite,
    CustomerDocument,
    CustomerProfile,
    KycApplication,
)
from app.modules.customers.validators import (
    MAX_SITES,
    FieldErrors,
    clean_text,
    mask_document_number,
    validate_address,
    validate_document_number,
    validate_email,
    validate_mobile,
    validate_name,
)
from app.modules.merchants.models import Merchant
from app.modules.users.models import User
from app.shared.business.actor import BusinessActor
from app.shared.business.audit import BusinessAuditor
from app.shared.business.transitions import StatusMachine
from app.shared.crypto import FieldCipher
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications import (
    NotificationOutboxWriter,
    application_received,
    new_kyc_application,
)

ACCOUNT_STATE = StatusMachine("customer account", ACCOUNT_TRANSITIONS)
CUSTOMER_ROLE = "customer"
# Staff channels. A number already used by staff cannot become a customer login, because the
# same user row would then carry both a staff role and a customer role.
STAFF_ROLES = {"super_admin", "manager", "salesperson", "godown_stock_manager", "accountant", "driver", "helper"}


@dataclass
class ValidatedRegistration:
    """The result of validating a registration body, ready to be written.

    Produced by one function for both actors, so a rule can never apply to only one of them.
    """

    customer_type: CustomerType
    business_name: str
    owner_name: str
    email: str | None
    address: dict
    documents: list[tuple[KycDocumentType, str, CustomerDocument]] = field(default_factory=list)
    sites: list[dict] = field(default_factory=list)
    gstin: str | None = None


class CustomerRegistrationService:
    """Shared primitives plus the two actor-specific commands."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        cipher: FieldCipher,
        documents: DocumentAccessService,
        auditor: BusinessAuditor | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.documents = documents
        self.auditor = auditor
        self.codes = CustomerCodeAllocator(session)
        self.notifications = NotificationOutboxWriter(session)

    # --- shared validation --------------------------------------------------------------

    async def validate(
        self,
        request: CustomerRegistrationRequest,
        actor: BusinessActor,
        *,
        require_documents: bool = True,
    ) -> ValidatedRegistration:
        """Validate a registration body for either actor.

        `require_documents` is false while a self-registering customer is still filling the
        form; it becomes true at submit. The validation of each *supplied* document is the
        same either way.
        """
        errors = FieldErrors()
        customer_type = request.customer_type
        business_name = validate_name(request.business_name, "businessName", errors)
        owner_name = validate_name(request.owner_name, "ownerName", errors)
        email = validate_email(request.email, errors)
        address = validate_address(request.delivery_address, errors)
        documents = await self._validate_documents(request.documents, customer_type, actor, errors, require=require_documents)
        sites = self._validate_sites(request.sites, customer_type, address, errors)
        gstin = next((number for kind, number, _ in documents if kind is KycDocumentType.GST), None)
        errors.raise_if_any()
        return ValidatedRegistration(
            customer_type=customer_type,
            business_name=business_name,
            owner_name=owner_name,
            email=email,
            address=address,
            documents=documents,
            sites=sites,
            gstin=gstin,
        )

    async def _validate_documents(
        self,
        submissions: list[DocumentSubmission],
        customer_type: CustomerType,
        actor: BusinessActor,
        errors: FieldErrors,
        *,
        require: bool,
    ) -> list[tuple[KycDocumentType, str, CustomerDocument]]:
        required = REQUIRED_DOCUMENTS[customer_type]
        supplied = {submission.type: submission for submission in submissions}
        for extra in set(supplied) - set(required):
            # A retail applicant sending an FSSAI licence is refused rather than ignored:
            # silently dropping it would leave the customer believing it was submitted.
            errors.add(
                f"doc.{extra.value}",
                "not_applicable",
                f"A {customer_type.value.lower()} customer does not submit a {extra.value} document.",
            )
        resolved: list[tuple[KycDocumentType, str, CustomerDocument]] = []
        for document_type in required:
            submission = supplied.get(document_type)
            if submission is None:
                if require:
                    errors.add(f"doc.{document_type.value}", "required", f"Upload the {document_type.value} document.")
                continue
            number = validate_document_number(document_type, submission.number, errors)
            upload_id = submission.upload_id
            if not upload_id:
                errors.add(f"doc.{document_type.value}.file", "required", "Upload the document file first.")
                continue
            try:
                upload = await self.documents.attachable(actor, upload_id, document_type)
            except ApiError as exc:
                errors.fields.extend(exc.detail.get("fields") or [])
                continue
            if number is not None:
                resolved.append((document_type, number, upload))
        return resolved

    def _validate_sites(
        self,
        submissions: list[SiteSubmission],
        customer_type: CustomerType,
        address: dict,
        errors: FieldErrors,
    ) -> list[dict]:
        if customer_type is CustomerType.RETAIL:
            if submissions:
                errors.add("sites", "not_applicable", "Retail customers do not have delivery sites.")
            return []
        if not submissions:
            errors.add("sites", "required", "Add at least one delivery site.")
            return []
        if len(submissions) > MAX_SITES:
            errors.add("sites", "too_many", f"Add at most {MAX_SITES} delivery sites.")
            return []

        sites: list[dict] = []
        seen: set[tuple] = set()
        for index, submission in enumerate(submissions):
            prefix = f"sites.{index}"
            name = validate_name(submission.name, f"{prefix}.name", errors)
            site_address = validate_address(submission.address, errors, prefix=f"{prefix}.address")
            contact_mobile = None
            if submission.contact_mobile and str(submission.contact_mobile).strip():
                contact_mobile = validate_mobile(submission.contact_mobile, errors, field=f"{prefix}.contactMobile")
            # Two sites with the same name at the same address are a duplicated row in the
            # form, not two real locations; accepting them would make dispatch ambiguous.
            fingerprint = (name.casefold(), site_address["line1"].casefold(), site_address["pincode"])
            if fingerprint in seen:
                errors.add(f"{prefix}.name", "duplicate", "This site is already in the list.")
                continue
            seen.add(fingerprint)
            sites.append(
                {
                    "name": name,
                    "address": site_address,
                    "contact_name": clean_text(submission.contact_name) or None,
                    "contact_mobile": contact_mobile,
                    "is_primary": bool(submission.is_primary),
                }
            )

        primaries = [site for site in sites if site["is_primary"]]
        if not primaries and sites:
            # The app sends the primary site first and may omit the flag entirely, so the
            # first site is promoted rather than rejecting an otherwise valid submission.
            sites[0]["is_primary"] = True
        elif len(primaries) > 1:
            errors.add("sites", "multiple_primary", "Mark exactly one site as the primary site.")
        if sites and not any(site["is_primary"] for site in sites):
            errors.add("sites", "primary_required", "Mark one site as the primary site.")
        primary = next((site for site in sites if site["is_primary"]), None)
        if primary and primary["address"]["pincode"] != address["pincode"]:
            # Spec: the primary site represents the registered delivery address. A different
            # pincode means one of the two is wrong, and dispatch would follow the wrong one.
            errors.add(
                "sites.0.address.pincode",
                "primary_mismatch",
                "The primary site must be at the registered delivery address.",
            )
        return sites

    # --- shared write primitives ---------------------------------------------------------

    def apply_profile_fields(self, profile: CustomerProfile, data: ValidatedRegistration, now: datetime) -> None:
        """Write the validated business fields onto a profile row.

        Status, pricing tier, merchant and code are **not** written here. They are decided by
        the workflow, never by the request, which is what makes mass assignment impossible.
        """
        profile.customer_type = data.customer_type.value
        profile.name = data.business_name
        profile.owner_name = data.owner_name
        profile.email = data.email
        profile.gst_number = data.gstin
        profile.address_line1 = data.address["line1"]
        profile.address_line2 = data.address["line2"]
        profile.address_city = data.address["city"]
        profile.address_state = data.address["state"]
        profile.address_pincode = data.address["pincode"]
        profile.updated_at = now

    def link_documents(self, profile: CustomerProfile, data: ValidatedRegistration, now: datetime) -> None:
        """Finalize each staged upload onto the customer.

        The identifier is encrypted, masked and hashed here, and `finalized_at` is stamped so
        the same upload can never be attached to a second registration.
        """
        for document_type, number, upload in data.documents:
            upload.customer_id = profile.id
            upload.merchant_id = profile.merchant_id
            upload.number_encrypted = self.cipher.encrypt(number)
            upload.number_masked = mask_document_number(document_type, number)
            upload.number_lookup_hash = self.cipher.lookup_hash(number)
            # The legacy plaintext column is explicitly cleared, so a row that predates
            # encryption does not keep a readable copy after being re-submitted.
            upload.document_number = None
            upload.status = DocumentStatus.UPLOADED.value
            upload.finalized_at = now
            upload.updated_at = now

    async def replace_sites(self, profile: CustomerProfile, data: ValidatedRegistration, now: datetime) -> None:
        """Set the customer's delivery sites to exactly what was submitted."""
        existing = await self.session.scalars(
            select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == profile.id)
        )
        for site in existing:
            # Soft-deleted rather than deleted: a past order may reference the site, and the
            # delivery address it was sent to must remain readable.
            site.is_active = False
            site.is_primary = False
            site.updated_at = now
        for site in data.sites:
            self.session.add(
                CustomerDeliverySite(
                    id=str(uuid4()),
                    customer_id=profile.id,
                    name=site["name"],
                    address_line1=site["address"]["line1"],
                    address_line2=site["address"]["line2"],
                    address_city=site["address"]["city"],
                    address_state=site["address"]["state"],
                    address_pincode=site["address"]["pincode"],
                    contact_name=site["contact_name"],
                    contact_mobile=site["contact_mobile"],
                    is_primary=site["is_primary"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def open_application(self, profile: CustomerProfile, submitted_by: str, now: datetime) -> KycApplication:
        """Return the customer's pending application, creating one only if none is open.

        This is what makes submit idempotent: a retried request finds the existing pending
        row instead of queueing a second review for the same customer.
        """
        existing = await self.session.scalar(
            select(KycApplication).where(
                KycApplication.customer_id == profile.id,
                KycApplication.status == ApplicationStatus.PENDING.value,
            )
        )
        if existing is not None:
            return existing
        application = KycApplication(
            id=str(uuid4()),
            customer_id=profile.id,
            merchant_id=profile.merchant_id,
            status=ApplicationStatus.PENDING.value,
            submitted_at=now,
            reviewed_at=None,
            reviewed_by_user_id=None,
            reviewed_by_name=None,
            rejection_reason=None,
            submitted_by_user_id=submitted_by,
            created_at=now,
            updated_at=now,
        )
        self.session.add(application)
        return application

    def move_to_review(self, profile: CustomerProfile, now: datetime) -> None:
        ACCOUNT_STATE.require_move(profile.status, CUSTOMER_UNDER_REVIEW)
        profile.status = CUSTOMER_UNDER_REVIEW
        profile.kyc_status = KycStatus.PENDING.value
        profile.rejection_reason = None
        profile.submitted_at = now
        profile.updated_at = now

    async def ensure_code(self, profile: CustomerProfile, customer_type: CustomerType) -> None:
        """Allocate the display code once. A resubmission keeps the code it already has."""
        if not profile.code:
            profile.code = await self.codes.allocate(customer_type)

    def queue_submission_events(
        self, profile: CustomerProfile, application: KycApplication, *, added_by: str | None = None
    ) -> None:
        self.notifications.queue(application_received(profile.id, profile.name or "your business", application.id))
        if profile.merchant_id:
            self.notifications.queue(
                new_kyc_application(profile.merchant_id, application.id, profile.name or "A customer", added_by)
            )

    # --- command: customer self-registration ---------------------------------------------

    async def save_self_profile(
        self,
        profile: CustomerProfile,
        request: CustomerRegistrationRequest,
        actor: BusinessActor,
        *,
        verified_mobile: str,
    ) -> None:
        """Save a self-registering customer's own business details.

        The mobile number is taken from `verified_mobile`, which the caller reads from the
        onboarding session. A `mobile` in the body is only ever compared against it, so a
        customer can never create a profile for a number they did not verify.

        Documents are not required yet - the form is still being filled in - but any document
        that *is* supplied goes through exactly the same validation it will face at submit.
        """
        self._require_own_mobile(request, verified_mobile)
        if profile.status not in EDITABLE_ACCOUNT_STATUSES:
            raise ApiError("REGISTRATION_NOT_EDITABLE", status.HTTP_409_CONFLICT)

        data = await self.validate(request, actor, require_documents=False)
        now = datetime.now(UTC)
        self.apply_profile_fields(profile, data, now)
        self.link_documents(profile, data, now)
        await self.replace_sites(profile, data, now)
        if profile.registered_at is None:
            profile.registered_at = now

    async def submit_self_registration(
        self,
        profile: CustomerProfile,
        actor: BusinessActor,
    ) -> KycApplication:
        """Submit the **stored** registration for review.

        Validation reads the saved profile rather than a request body, because by this point
        there is no body: the app has already saved everything and is pressing Submit. That
        also means a client cannot slip different values past the checks at the last moment.

        Retrying is safe. A profile already under review returns its existing pending
        application instead of opening a second one.
        """
        if profile.status == CUSTOMER_UNDER_REVIEW:
            now = datetime.now(UTC)
            return await self.open_application(profile, actor.user_id, now)
        if profile.status not in EDITABLE_ACCOUNT_STATUSES:
            raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT)

        await self._require_submittable(profile)
        now = datetime.now(UTC)
        if profile.customer_type:
            await self.ensure_code(profile, CustomerType(profile.customer_type))
        self.move_to_review(profile, now)
        application = await self.open_application(profile, actor.user_id, now)
        self.queue_submission_events(profile, application)
        if self.auditor:
            await self.auditor.record(
                "customer.registration_submitted",
                actor=actor,
                entity_type="customer_profile",
                entity_id=profile.id,
                message="Customer submitted their registration for review",
            )
        return application

    async def missing_for_submit(self, profile: CustomerProfile) -> tuple[list[str], list[str]]:
        """What the Application Status screen lists as still outstanding.

        Field names follow whichever contract the registration is on, because the app
        highlights an input by the name it sent: a legacy draft gets `name` and
        `customer_type`, a spec registration gets `businessName` and `customerType`. The same
        two lists drive the 422 from `_require_submittable`, so the screen and the error can
        never disagree about what is left to do.
        """
        strict = self._on_kyc_contract(profile)
        required_fields = (
            {
                "businessName": profile.name,
                "customerType": profile.customer_type,
                "merchantCode": profile.merchant_code,
                "ownerName": profile.owner_name,
                "deliveryAddress.line1": profile.address_line1,
                "deliveryAddress.city": profile.address_city,
                "deliveryAddress.state": profile.address_state,
                "deliveryAddress.pincode": profile.address_pincode,
            }
            if strict
            else {
                "name": profile.name,
                "customer_type": profile.customer_type,
                "merchant_code": profile.merchant_code,
            }
        )
        missing_fields = [name for name, value in required_fields.items() if not value]

        missing_documents: list[str] = []
        if strict and profile.customer_type:
            linked = {
                document.document_type
                for document in await self.session.scalars(
                    select(CustomerDocument).where(
                        CustomerDocument.customer_id == profile.id,
                        CustomerDocument.finalized_at.is_not(None),
                    )
                )
            }
            required = REQUIRED_DOCUMENTS[CustomerType(profile.customer_type)]
            missing_documents = [kind.value for kind in required if kind.value not in linked]
        return missing_fields, missing_documents

    @staticmethod
    def _on_kyc_contract(profile: CustomerProfile) -> bool:
        """Whether this registration is being made through the full API_SPEC contract.

        Detected from data only an owner name or an address could have come from, so there is
        no flag a client can set to opt out of the stricter rules.
        """
        return bool(profile.owner_name or profile.address_line1)

    async def _require_submittable(self, profile: CustomerProfile) -> None:
        missing_fields, missing_documents = await self.missing_for_submit(profile)
        fields = [
            {"field": name, "code": "missing", "message": "This field is required before submitting."}
            for name in missing_fields
        ]
        fields += [
            {"field": f"doc.{kind}", "code": "missing", "message": f"Upload the {kind} document before submitting."}
            for kind in missing_documents
        ]
        if fields:
            raise ApiError("REGISTRATION_INCOMPLETE", status.HTTP_422_UNPROCESSABLE_CONTENT, fields=fields)
        if profile.customer_type == CustomerType.INDUSTRIAL.value and self._on_kyc_contract(profile):
            primaries = list(
                await self.session.scalars(
                    select(CustomerDeliverySite).where(
                        CustomerDeliverySite.customer_id == profile.id,
                        CustomerDeliverySite.is_active.is_(True),
                        CustomerDeliverySite.is_primary.is_(True),
                    )
                )
            )
            if len(primaries) != 1:
                raise ApiError(
                    "REGISTRATION_INCOMPLETE",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    fields=[{"field": "sites", "code": "primary_required", "message": "Add exactly one primary delivery site."}],
                )

    @staticmethod
    def _require_own_mobile(request: CustomerRegistrationRequest, verified_mobile: str) -> None:
        if not request.mobile:
            return
        errors = FieldErrors()
        supplied = validate_mobile(request.mobile, errors)
        errors.raise_if_any()
        if supplied != verified_mobile:
            raise ApiError(
                "PERMISSION_DENIED",
                status.HTTP_403_FORBIDDEN,
                "The mobile number does not match the verified number.",
            )

    # --- command: merchant staff creates a customer ---------------------------------------

    async def create_customer_by_merchant(
        self,
        request: CustomerRegistrationRequest,
        actor: BusinessActor,
        merchant: Merchant,
    ) -> tuple[CustomerProfile, KycApplication]:
        """Create a customer, its login identity and a pending application, in one go.

        Every ownership field comes from the authenticated actor. The body supplies business
        data and the customer's mobile number, and nothing else.
        """
        errors = FieldErrors()
        mobile = validate_mobile(request.mobile, errors)
        errors.raise_if_any()
        assert mobile is not None  # validate_mobile raised otherwise
        await self._reject_staff_mobile(mobile)
        await self._reject_existing_customer(mobile)

        data = await self.validate(request, actor, require_documents=True)
        now = datetime.now(UTC)
        user = await self._link_or_create_customer_user(mobile, data.owner_name, now)
        profile = CustomerProfile(
            id=str(uuid4()),
            code=None,
            user_id=user.id,
            merchant_id=merchant.id,
            merchant_code=merchant.code,
            mobile_number=mobile,
            # Staff-entered customers start pending like any other; the same reviewer step
            # applies, so a salesperson cannot approve their own entry by creating it.
            status=CUSTOMER_PROFILE_INCOMPLETE,
            kyc_status=KycStatus.NOT_SUBMITTED.value,
            pricing_tier=PricingTier.STANDARD.value,
            rejection_reason=None,
            mobile_verified_at=None,
            submitted_at=None,
            reviewed_by=None,
            reviewed_at=None,
            approved_at=None,
            registered_at=now,
            created_at=now,
            updated_at=now,
        )
        self.apply_profile_fields(profile, data, now)
        self.session.add(profile)
        try:
            # A savepoint, so a concurrent create losing the unique-mobile race becomes a
            # clean 409 instead of poisoning the caller's transaction.
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            if profile in self.session:
                self.session.expunge(profile)
            raise self._duplicate_mobile() from exc

        await self.ensure_code(profile, data.customer_type)
        self.link_documents(profile, data, now)
        await self.replace_sites(profile, data, now)
        self.move_to_review(profile, now)
        application = await self.open_application(profile, actor.user_id, now)
        self.queue_submission_events(profile, application, added_by=actor.display_name)
        if self.auditor:
            await self.auditor.record(
                "customer.created_by_staff",
                actor=actor,
                entity_type="customer_profile",
                entity_id=profile.id,
                message="Customer created by merchant staff",
            )
        return profile, application

    # --- guards shared by the staff path ---------------------------------------------------

    @staticmethod
    def _duplicate_mobile() -> ApiError:
        return ApiError(
            "REGISTRATION_PROFILE_EXISTS",
            status.HTTP_409_CONFLICT,
            "A customer with this mobile already exists.",
            fields=[{"field": "mobile", "code": "duplicate", "message": "A customer with this mobile already exists."}],
        )

    async def _reject_staff_mobile(self, mobile: str) -> None:
        user = await self.session.scalar(select(User).where(User.mobile_number == mobile))
        if user is not None and user.role in STAFF_ROLES:
            raise ApiError(
                "VALIDATION_ERROR",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[{"field": "mobile", "code": "staff_number", "message": "This number belongs to MBGA staff."}],
            )

    async def _reject_existing_customer(self, mobile: str) -> None:
        existing = await self.session.scalar(select(CustomerProfile.id).where(CustomerProfile.mobile_number == mobile))
        if existing is not None:
            raise self._duplicate_mobile()

    async def _link_or_create_customer_user(self, mobile: str, owner_name: str, now: datetime) -> User:
        """Reuse the customer's existing login if there is one, otherwise create it.

        A customer who once started a registration already has a user row; creating a second
        would split their sign-in. Reuse never touches roles — the customer role is granted
        only on approval, by the review service, so this path cannot escalate anyone.
        """
        user = await self.session.scalar(select(User).where(User.mobile_number == mobile))
        if user is not None:
            if not user.full_name:
                user.full_name = owner_name
                user.updated_at = now
            return user
        user = User(
            id=str(uuid4()),
            email=None,
            username=None,
            full_name=owner_name,
            mobile_number=mobile,
            country_code="+91",
            password_hash=None,
            role=CUSTOMER_ROLE,
            # Not ACTIVE: the customer can sign in and see "Verification Pending", but the
            # account only becomes fully usable when a reviewer approves it.
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self.session.add(user)
        await self.session.flush()
        return user
