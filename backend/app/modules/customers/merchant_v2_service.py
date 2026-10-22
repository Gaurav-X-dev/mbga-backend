"""Load and review V2 KYC applications without changing the V1 response contract."""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.business_schemas import CustomerResponse, KycApplicationResponse
from app.modules.customers.constants import DOCUMENT_APPROVED, to_mobile_document_status
from app.modules.customers.mapping import CustomerViewLoader, application_response
from app.modules.customers.merchant_v2_schemas import (
    KycDocumentResponseV2,
    MerchantCustomerResponseV2,
    MerchantKycApplicationResponseV2,
)
from app.modules.customers.models import CustomerDocument, CustomerProfile, KycApplication
from app.modules.customers.review import KycReviewService
from app.modules.customers.v2_models import CustomerDocumentFileV2
from app.modules.customers.v2_schemas import DocumentFileResponseV2, DocumentSide, UploadSource
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError


class MerchantKycV2Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.loader = CustomerViewLoader(session)

    async def customer(self, profile: CustomerProfile) -> MerchantCustomerResponseV2:
        base = await self.loader.customer_view(profile)
        primary_documents = await self.loader.documents_for([profile.id])
        documents = await self._documents(
            profile.id, primary_documents.get(profile.id, [])
        )
        return self._with_customer_documents(base, documents)

    async def application(
        self, application: KycApplication, profile: CustomerProfile
    ) -> MerchantKycApplicationResponseV2:
        sites = await self.loader.sites_for([profile.id])
        primary_documents = await self.loader.documents_for([profile.id])
        base = application_response(
            application,
            profile,
            sites=sites.get(profile.id, []),
            documents=primary_documents.get(profile.id, []),
        )
        documents = await self._documents(profile.id, primary_documents.get(profile.id, []))
        return self._with_documents(base, documents)

    async def applications(
        self,
        applications: list[KycApplication],
        profiles: dict[str, CustomerProfile],
    ) -> list[MerchantKycApplicationResponseV2]:
        customer_ids = [
            application.customer_id
            for application in applications
            if application.customer_id in profiles
        ]
        sites = await self.loader.sites_for(customer_ids)
        primary_documents = await self.loader.documents_for(customer_ids)
        mappings, files = await self._mapping_context(customer_ids)
        result: list[MerchantKycApplicationResponseV2] = []
        for application in applications:
            profile = profiles.get(application.customer_id)
            if profile is not None:
                primaries = primary_documents.get(profile.id, [])
                base = application_response(
                    application,
                    profile,
                    sites=sites.get(profile.id, []),
                    documents=primaries,
                )
                documents = self._document_responses(
                    primaries,
                    mappings.get(profile.id, []),
                    files,
                )
                result.append(self._with_documents(base, documents))
        return result

    async def _documents(
        self, customer_id: str, primary_documents: list[CustomerDocument]
    ) -> list[KycDocumentResponseV2]:
        mappings, files = await self._mapping_context([customer_id])
        return self._document_responses(
            primary_documents,
            mappings.get(customer_id, []),
            files,
        )

    async def _mapping_context(
        self, customer_ids: list[str]
    ) -> tuple[dict[str, list[CustomerDocumentFileV2]], dict[str, CustomerDocument]]:
        if not customer_ids:
            return {}, {}
        mappings = list(
            await self.session.scalars(
                select(CustomerDocumentFileV2)
                .where(
                    CustomerDocumentFileV2.customer_id.in_(customer_ids),
                    CustomerDocumentFileV2.superseded_at.is_(None),
                )
                .order_by(
                    CustomerDocumentFileV2.customer_id,
                    CustomerDocumentFileV2.document_type,
                    CustomerDocumentFileV2.sort_order,
                )
            )
        )
        grouped: dict[str, list[CustomerDocumentFileV2]] = {}
        for mapping in mappings:
            grouped.setdefault(mapping.customer_id, []).append(mapping)
        file_ids = [mapping.file_id for mapping in mappings]
        documents = (
            list(
                await self.session.scalars(
                    select(CustomerDocument).where(CustomerDocument.file_id.in_(file_ids))
                )
            )
            if file_ids
            else []
        )
        return grouped, {document.file_id: document for document in documents}

    def _document_responses(
        self,
        primary_documents: list[CustomerDocument],
        mappings: list[CustomerDocumentFileV2],
        by_file: dict[str, CustomerDocument],
    ) -> list[KycDocumentResponseV2]:
        by_type: dict[str, list[CustomerDocumentFileV2]] = {}
        for mapping in mappings:
            by_type.setdefault(mapping.document_type, []).append(mapping)
        responses: list[KycDocumentResponseV2] = []
        for primary in primary_documents:
            mapped = by_type.get(primary.document_type, [])
            file_responses = [
                self._file_response(by_file[mapping.file_id], mapping)
                for mapping in mapped
                if mapping.file_id in by_file
            ]
            if not file_responses:
                file_responses = [
                    DocumentFileResponseV2(
                        file_id=primary.file_id or primary.id,
                        file_name=primary.original_filename,
                        file_size=primary.file_size,
                        content_type=primary.mime_type,
                        side=DocumentSide.FRONT,
                        source=UploadSource.FILE_PICKER,
                        sort_order=1,
                    )
                ]
            responses.append(
                KycDocumentResponseV2(
                    id=primary.id,
                    type=primary.document_type,
                    number_masked=primary.number_masked or "",
                    status=to_mobile_document_status(primary.status),
                    files=file_responses,
                )
            )
        return responses

    @staticmethod
    def _file_response(
        document: CustomerDocument, mapping: CustomerDocumentFileV2
    ) -> DocumentFileResponseV2:
        return DocumentFileResponseV2(
            file_id=document.file_id or document.id,
            file_name=document.original_filename,
            file_size=document.file_size,
            content_type=document.mime_type,
            side=DocumentSide(mapping.side),
            source=UploadSource(mapping.source),
            sort_order=mapping.sort_order,
        )

    @staticmethod
    def _with_documents(
        base: KycApplicationResponse, documents: list[KycDocumentResponseV2]
    ) -> MerchantKycApplicationResponseV2:
        return MerchantKycApplicationResponseV2(
            **base.model_dump(exclude={"documents"}), documents=documents
        )

    @staticmethod
    def _with_customer_documents(
        base: CustomerResponse, documents: list[KycDocumentResponseV2]
    ) -> MerchantCustomerResponseV2:
        return MerchantCustomerResponseV2(
            **base.model_dump(exclude={"documents"}), documents=documents
        )

    async def approve(
        self,
        application_id: str,
        actor: BusinessActor,
        review: KycReviewService,
    ) -> CustomerProfile:
        _application, profile = await review.locked_application(application_id, actor)
        secondary = await self._mapped_files(profile.id)
        for document in secondary:
            if document.finalized_at is None:
                raise ApiError(
                    "DOCUMENTS_PENDING_APPROVAL",
                    status.HTTP_409_CONFLICT,
                    "A document image has not been finalized.",
                )
            if not review._scan_is_approvable(document.scan_status):
                raise ApiError(
                    "DOCUMENT_SCAN_PENDING",
                    status.HTTP_409_CONFLICT,
                    "A document image has not passed the security scan.",
                )
        await review.approve(profile, actor)
        now = datetime.now(UTC)
        for document in secondary:
            document.status = DOCUMENT_APPROVED
            document.reviewed_by = actor.user_id
            document.reviewed_at = now
            document.updated_at = now
        return profile

    async def reject(
        self,
        application_id: str,
        actor: BusinessActor,
        review: KycReviewService,
        reason: str,
    ) -> CustomerProfile:
        _application, profile = await review.locked_application(application_id, actor)
        await review.reject(profile, actor, reason)
        return profile

    async def _mapped_files(self, customer_id: str) -> list[CustomerDocument]:
        file_ids = list(
            await self.session.scalars(
                select(CustomerDocumentFileV2.file_id).where(
                    CustomerDocumentFileV2.customer_id == customer_id,
                    CustomerDocumentFileV2.superseded_at.is_(None),
                )
            )
        )
        if not file_ids:
            return []
        return list(
            await self.session.scalars(
                select(CustomerDocument).where(CustomerDocument.file_id.in_(file_ids))
            )
        )
