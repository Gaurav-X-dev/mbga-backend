"""Application service for v2 two-image KYC registration."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.business_schemas import CustomerRegistrationRequest, DocumentSubmission
from app.modules.customers.constants import (
    ALLOWED_DOCUMENTS,
    CustomerType,
    DocumentStatus,
)
from app.modules.customers.documents import DocumentAccessService
from app.modules.customers.models import CustomerDocument, CustomerProfile, KycApplication
from app.modules.customers.registration import CustomerRegistrationService, ValidatedRegistration
from app.modules.customers.v2_models import CustomerDocumentFileV2
from app.modules.customers.v2_schemas import DocumentSubmissionV2
from app.modules.customers.validators import (
    FieldErrors,
    mask_document_number,
    validate_document_number,
)
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError

if TYPE_CHECKING:
    from app.modules.merchants.models import Merchant


@dataclass
class PreparedDocumentV2:
    submission: DocumentSubmissionV2
    number: str
    uploads: list[CustomerDocument]
    current_file_ids: set[str]

    @property
    def primary(self) -> CustomerDocument:
        return self.uploads[0]


class CustomerRegistrationV2Service:
    def __init__(
        self,
        session: AsyncSession,
        *,
        base: CustomerRegistrationService,
        access: DocumentAccessService,
    ) -> None:
        self.session = session
        self.base = base
        self.access = access

    async def prepare(
        self,
        profile: CustomerProfile | None,
        actor: BusinessActor,
        submissions: list[DocumentSubmissionV2],
        customer_type: CustomerType,
    ) -> list[PreparedDocumentV2]:
        errors = FieldErrors()
        seen_types: set = set()
        prepared: list[PreparedDocumentV2] = []
        allowed = set(ALLOWED_DOCUMENTS[customer_type])

        for doc_index, submission in enumerate(submissions):
            prefix = f"documents.{doc_index}"
            if submission.type in seen_types:
                errors.add(prefix, "duplicate_type", "Submit each document type only once.")
                continue
            seen_types.add(submission.type)
            if submission.type not in allowed:
                errors.add(prefix, "not_applicable", "This document is not applicable to the customer type.")
                continue
            sides = [item.side for item in submission.files]
            file_ids = [item.file_id for item in submission.files]
            if len(set(sides)) != len(sides):
                errors.add(f"{prefix}.files", "duplicate_side", "Document cannot have duplicate side images.")
                continue
            if len(set(file_ids)) != len(file_ids):
                errors.add(f"{prefix}.files", "duplicate_file", "The same image cannot be submitted twice.")
                continue
            number = validate_document_number(submission.type, submission.number, errors)
            if number is None:
                continue

            current = (
                list(
                    await self.session.scalars(
                        select(CustomerDocumentFileV2).where(
                            CustomerDocumentFileV2.customer_id == profile.id,
                            CustomerDocumentFileV2.document_type == submission.type.value,
                            CustomerDocumentFileV2.superseded_at.is_(None),
                        )
                    )
                )
                if profile is not None
                else []
            )
            current_ids = {row.file_id for row in current}
            uploads: list[CustomerDocument] = []
            for file_index, item in enumerate(submission.files):
                if item.file_id in current_ids:
                    upload = await self.session.scalar(
                        select(CustomerDocument).where(CustomerDocument.file_id == item.file_id)
                    )
                    if upload is None:
                        errors.add(f"{prefix}.files.{file_index}.fileId", "not_found", "Upload this document again.")
                        continue
                else:
                    try:
                        upload = await self.access.attachable(actor, item.file_id, submission.type)
                    except ApiError:
                        errors.add(f"{prefix}.files.{file_index}.fileId", "not_found", "Upload this document again.")
                        continue
                uploads.append(upload)
            if len(uploads) == len(submission.files):
                prepared.append(PreparedDocumentV2(submission, number, uploads, current_ids))
        errors.raise_if_any()
        return prepared

    async def create_customer_by_merchant(
        self,
        request: CustomerRegistrationRequest,
        actor: BusinessActor,
        merchant: "Merchant",
    ) -> tuple[CustomerProfile, KycApplication]:
        prepared = await self.prepare(None, actor, request.documents, request.customer_type)
        primary_submissions = [
            DocumentSubmission(
                type=item.submission.type,
                number=item.number,
                fileId=item.primary.file_id,
            )
            for item in prepared
        ]
        base_request = request.model_copy(update={"documents": primary_submissions})
        profile, application = await self.base.create_customer_by_merchant(
            base_request, actor, merchant
        )
        await self._replace_mappings(profile, prepared)
        return profile, application

    async def save(
        self,
        profile: CustomerProfile,
        request: CustomerRegistrationRequest,
        actor: BusinessActor,
        prepared: list[PreparedDocumentV2],
        *,
        verified_mobile: str,
    ) -> None:
        # Only newly selected primaries enter the frozen v1 service. Existing primaries are
        # already finalized and would correctly be rejected as reusable staged uploads.
        primary_submissions = [
            DocumentSubmission(type=item.submission.type, number=item.number, fileId=item.primary.file_id)
            for item in prepared
            if item.primary.file_id not in item.current_file_ids
        ]
        base_request = request.model_copy(update={"documents": primary_submissions})
        await self.base.save_self_profile(
            profile, base_request, actor, verified_mobile=verified_mobile
        )
        uniqueness_data = ValidatedRegistration(
            customer_type=request.customer_type,
            business_name=request.business_name,
            owner_name=request.owner_name,
            email=request.email,
            address={},
            documents=[
                (item.submission.type, item.number, item.primary) for item in prepared
            ],
        )
        await self.base.ensure_numbers_are_unique(profile, uniqueness_data)
        # `apply_profile_fields` derives GSTIN from the documents it received. Preserve the
        # value when an idempotent v2 save reuses the already-linked GST primary.
        gst = next((item.number for item in prepared if item.submission.type.value == "GST"), None)
        if gst is not None:
            profile.gst_number = gst
        await self._replace_mappings(profile, prepared)

    async def _replace_mappings(
        self, profile: CustomerProfile, prepared: list[PreparedDocumentV2]
    ) -> None:
        now = datetime.now(UTC)
        for item in prepared:
            current = list(
                await self.session.scalars(
                    select(CustomerDocumentFileV2).where(
                        CustomerDocumentFileV2.customer_id == profile.id,
                        CustomerDocumentFileV2.document_type == item.submission.type.value,
                        CustomerDocumentFileV2.superseded_at.is_(None),
                    )
                )
            )
            current_by_file = {row.file_id: row for row in current}
            requested_ids = {upload.file_id for upload in item.uploads}
            for row in current:
                if row.file_id not in requested_ids:
                    row.superseded_at = now
                    row.updated_at = now

            primary = item.primary
            if primary.customer_id != profile.id:
                await self.base._supersede_previous(profile, item.submission.type, primary, now)
                primary.customer_id = profile.id
            primary.merchant_id = profile.merchant_id
            primary.number_encrypted = self.base.cipher.encrypt(item.number)
            primary.number_masked = mask_document_number(item.submission.type, item.number)
            primary.number_lookup_hash = self.base.cipher.lookup_hash(item.number)
            primary.document_number = None
            for index, (file_data, upload) in enumerate(zip(item.submission.files, item.uploads, strict=True), start=1):
                if upload.finalized_at is None:
                    upload.finalized_at = now
                    upload.merchant_id = profile.merchant_id
                    upload.status = DocumentStatus.UPLOADED.value
                    upload.updated_at = now
                # Only the primary is linked through the v1 customer_id column. This keeps
                # the second image invisible to every frozen v1 list/response.
                if upload.file_id != primary.file_id:
                    upload.customer_id = None
                    upload.number_encrypted = primary.number_encrypted
                    upload.number_masked = primary.number_masked
                    upload.number_lookup_hash = primary.number_lookup_hash
                    upload.document_number = None
                mapping = current_by_file.get(upload.file_id)
                if mapping is None:
                    mapping = CustomerDocumentFileV2(
                        id=str(uuid4()),
                        customer_id=profile.id,
                        document_type=item.submission.type.value,
                        file_id=upload.file_id,
                        superseded_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                    self.session.add(mapping)
                mapping.side = file_data.side.value
                mapping.source = file_data.source.value
                mapping.sort_order = index
                mapping.is_primary = index == 1
                mapping.updated_at = now
        await self.session.flush()
