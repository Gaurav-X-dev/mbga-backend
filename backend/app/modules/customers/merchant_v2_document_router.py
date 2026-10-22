"""Secure Merchant V2 access to primary and secondary KYC images."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.business_schemas import DocumentUrlResponse
from app.modules.customers.constants import UploadType
from app.modules.customers.dependencies import (
    AccessDep,
    ActorDep,
    StorageDep,
    UploadDep,
    get_auditor,
)
from app.modules.customers.v2_schemas import (
    DocumentSide,
    DocumentUploadResponseV2,
    UploadSource,
)
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.actor import BusinessActorResolver
from app.shared.business.audit import BusinessAuditor
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses
from app.shared.storage import UnsafeStorageKeyError

router = APIRouter(prefix="/documents", tags=["Merchant V2 Documents"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
VIEW_GUARDS = [
    Depends(require_login_channel(LoginChannel.MERCHANT)),
    Depends(require_permission("customers.review")),
    Depends(require_permission("customer_documents.review")),
]
CREATE_GUARDS = [
    Depends(require_login_channel(LoginChannel.MERCHANT)),
    Depends(require_permission("customers.create")),
]


@router.post(
    "",
    response_model=DocumentUploadResponseV2,
    status_code=status.HTTP_201_CREATED,
    dependencies=CREATE_GUARDS,
    responses=error_responses(401, 403, 413, 415, 422),
)
async def upload_document_v2(
    actor: ActorDep,
    service: UploadDep,
    auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
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


@router.get(
    "/{file_id}/url",
    response_model=DocumentUrlResponse,
    dependencies=VIEW_GUARDS,
    responses=error_responses(401, 403, 404),
)
async def document_url_v2(
    file_id: str,
    actor: ActorDep,
    access: AccessDep,
    storage: StorageDep,
    auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
    response: Response,
) -> DocumentUrlResponse:
    document = await access.readable(actor, file_id)
    await auditor.record(
        "customer_document.viewed",
        actor=actor,
        entity_type="customer_document",
        entity_id=file_id,
        message=f"Opened a {document.document_type} document image",
    )
    await session.commit()
    response.headers.update(NO_STORE)
    native = storage.signed_url(document.storage_key, expires_in=access.expires_in)
    if native:
        return DocumentUrlResponse(url=native, expires_in_seconds=access.expires_in)
    token, expires_in = access.grant(actor, document)
    base = str(request.base_url).rstrip("/")
    return DocumentUrlResponse(
        url=f"{base}/api/v2/merchant/documents/{file_id}/content?token={token}",
        expires_in_seconds=expires_in,
    )


@router.get(
    "/{file_id}/content",
    responses=error_responses(401, 403, 404, 410),
    response_class=StreamingResponse,
)
async def document_content_v2(
    file_id: str,
    token: str,
    access: AccessDep,
    storage: StorageDep,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    granted_file_id, viewer_id = access.verify(token)
    if granted_file_id != file_id:
        raise ApiError("DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    actor = await BusinessActorResolver(session).resolve_viewer(viewer_id, LoginChannel.MERCHANT)
    document = await access.readable(actor, file_id)
    try:
        stream = storage.open(document.storage_key)
    except (FileNotFoundError, UnsafeStorageKeyError) as exc:
        raise ApiError("DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND) from exc
    return StreamingResponse(
        stream,
        media_type=document.mime_type,
        headers={
            **NO_STORE,
            "Content-Disposition": f'inline; filename="{document.original_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
