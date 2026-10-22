"""V2-only upload endpoint with capture side/source metadata."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.modules.customers.constants import UploadType
from app.modules.customers.dependencies import CustomerActorDep, UploadDep, get_auditor
from app.modules.customers.v2_schemas import DocumentSide, DocumentUploadResponseV2, UploadSource
from app.shared.business.audit import BusinessAuditor
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/documents", tags=["Customer V2 Documents"])


@router.post(
    "",
    response_model=DocumentUploadResponseV2,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 413, 415, 422),
    summary="Upload a V2 KYC document image",
)
async def upload_document_v2(
    actor: CustomerActorDep,
    service: UploadDep,
    auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
    session: Annotated[object, Depends(get_db_session)],
    file: Annotated[UploadFile, File(description="PDF, JPG or PNG; at most 5 MB.")],
    type: Annotated[UploadType, Form()],
    side: Annotated[DocumentSide, Form()] = DocumentSide.FRONT,
    source: Annotated[UploadSource, Form()] = UploadSource.FILE_PICKER,
) -> DocumentUploadResponseV2:
    result = await service.upload(actor, file, type)
    await auditor.record(
        "customer_document_v2.uploaded",
        actor=actor,
        entity_type="customer_document",
        entity_id=result.file_id,
        message=f"Uploaded a {type.value} {side.value} document image",
    )
    await session.commit()
    return DocumentUploadResponseV2(
        file_id=result.file_id,
        file_name=result.file_name,
        content_type=result.content_type,
        size=result.size,
        side=side,
        source=source,
        uploaded_at=datetime.now(UTC),
    )
