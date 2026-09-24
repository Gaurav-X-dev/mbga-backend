"""Document upload and secure viewing, mounted on the customer and merchant channels.

Both channels mount the *same* handlers through `build_document_router`. Only the actor
dependency and the required permissions differ, which is the one difference that genuinely
exists between them — a merchant reviewer needs `customer_documents.review`, a customer needs
nothing beyond owning the file.

Routes stay channel-prefixed. An unprefixed `/documents` would be reachable with any channel's
token and would undo the channel isolation the auth layer provides.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.business_schemas import DocumentUploadResponse, DocumentUrlResponse
from app.modules.customers.constants import KycDocumentType
from app.modules.customers.dependencies import (
    AccessDep,
    ActorDep,
    CustomerActorDep,
    StorageDep,
    UploadDep,
    get_auditor,
)
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.actor import BusinessActorResolver
from app.shared.business.audit import BusinessAuditor
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses
from app.shared.storage import UnsafeStorageKeyError

# The reviewer screen opens a document; it must never be cached by a proxy or left in the
# browser's disk cache after the reviewer signs out.
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def build_document_router(channel: LoginChannel, *, view_permissions: tuple[str, ...] = ()) -> APIRouter:
    """Build the `/documents` routes for one channel."""
    router = APIRouter(prefix="/documents", tags=[f"{channel.value.title()} Documents"])
    actor_dependency = CustomerActorDep if channel is LoginChannel.CUSTOMER else ActorDep
    # The customer actor already locks the channel *and* admits the onboarding session that
    # registration uploads arrive on. `require_login_channel` would reject that session,
    # because it resolves a full app session first - so it is only added for merchants.
    guards = [] if channel is LoginChannel.CUSTOMER else [Depends(require_login_channel(channel))]
    view_guards = guards + [Depends(require_permission(name)) for name in view_permissions]

    @router.post(
        "",
        response_model=DocumentUploadResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=guards,
        responses=error_responses(401, 403, 413, 415, 422),
        summary="Upload a KYC document",
    )
    async def upload_document(
        actor: actor_dependency,
        service: UploadDep,
        auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
        session: Annotated[object, Depends(get_db_session)],
        file: Annotated[UploadFile, File(description="PDF, JPG or PNG, at most 5 MB.")],
        type: Annotated[KycDocumentType, Form(description="AADHAAR, PAN, FSSAI or GST.")],
    ) -> DocumentUploadResponse:
        result = await service.upload(actor, file, type)
        await auditor.record(
            "customer_document.uploaded",
            actor=actor,
            entity_type="customer_document",
            entity_id=result.file_id,
            # The document number is not known at upload time and is never audited anyway.
            message=f"Uploaded a {type.value} document",
        )
        await session.commit()
        return DocumentUploadResponse(
            file_id=result.file_id,
            file_name=result.file_name,
            content_type=result.content_type,
            size=result.size,
        )

    @router.get(
        "/{file_id}/url",
        response_model=DocumentUrlResponse,
        dependencies=view_guards,
        responses=error_responses(401, 403, 404),
        summary="Get a short-lived document URL",
    )
    async def document_url(
        file_id: str,
        actor: actor_dependency,
        access: AccessDep,
        storage: StorageDep,
        auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
        session: Annotated[object, Depends(get_db_session)],
        request: Request,
        response: Response,
    ) -> DocumentUrlResponse:
        document = await access.readable(actor, file_id)
        await auditor.record(
            "customer_document.viewed",
            actor=actor,
            entity_type="customer_document",
            entity_id=file_id,
            message=f"Opened a {document.document_type} document",
        )
        await session.commit()
        response.headers.update(NO_STORE)
        native = storage.signed_url(document.storage_key, expires_in=access.expires_in)
        if native:
            return DocumentUrlResponse(url=native, expires_in_seconds=access.expires_in)
        # The local provider cannot sign a URL, so the application signs a token for its own
        # streaming route instead. The path below is still authenticated; the token binds the
        # grant to this file and this viewer, and expires with the same window.
        token, expires_in = access.grant(actor, document)
        # Absolute, built from the request's own host, so the app can hand it straight to an
        # image view. A relative path would resolve against the app bundle, not the API.
        base = str(request.base_url).rstrip("/")
        prefix = f"{base}/api/v1/{channel.value.lower()}"
        return DocumentUrlResponse(
            url=f"{prefix}/documents/{file_id}/content?token={token}",
            expires_in_seconds=expires_in,
        )

    @router.get(
        "/{file_id}/content",
        responses=error_responses(401, 403, 404, 410),
        summary="Stream a document",
        response_class=StreamingResponse,
    )
    async def document_content(
        file_id: str,
        token: str,
        access: AccessDep,
        storage: StorageDep,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> StreamingResponse:
        """Serve the bytes to whoever holds a valid, unexpired signed link.

        Deliberately not behind the session dependency: a link that still needs an
        Authorization header cannot be handed to an image view, which is the whole point of
        §17.2. The link is not a weaker check, it is a different one - it is signed, expires
        in five minutes, names one file and one viewer, and access is re-verified below
        against live data, so a reviewer removed from the merchant loses the file at once.
        """
        granted_file_id, viewer_id = access.verify(token)
        if granted_file_id != file_id:
            raise ApiError("DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        actor = await BusinessActorResolver(session).resolve_viewer(viewer_id, channel)
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
                # `inline` so the reviewer sees it in the app; the filename is the sanitized
                # display name, never the storage key.
                "Content-Disposition": f'inline; filename="{document.original_filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
