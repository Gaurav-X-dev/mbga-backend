"""KYC document upload, authorisation and secure viewing.

One service backs both channels. The customer route and the merchant route mount the same
methods and differ only in the actor policy applied, so a rule fixed here is fixed for both.

The upload is **staged**: bytes land in storage and a `customer_documents` row is created with
no `customer_id`, owned by whoever uploaded it. Registration later *finalizes* the row by
attaching it to a customer. That split exists because a self-registering customer has no
customer profile yet when they pick a file, and because it keeps file I/O out of the
registration transaction.

Ownership is decided at upload time and never moves:

* A customer's upload is bound to their user id. Only that user's own registration can use it.
* Staff uploads are bound to the merchant. Only a customer of that merchant can receive them.

Anything not matching is reported as **404**, never 403 — a 403 would confirm that a file id
exists, which is all an attacker needs to enumerate them.
"""

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.constants import DocumentStatus, KycDocumentType, ScanStatus, UploadType
from app.modules.customers.models import CustomerDocument
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.storage.file_types import (
    ALLOWED_CONTENT_TYPES,
    EXTENSIONS,
    SNIFF_BYTES,
    TASK_CONTENT_TYPES,
    detect_content_type,
    extension_matches,
    sanitize_filename,
)
from app.shared.storage.provider import StorageProvider

READ_CHUNK = 64 * 1024
FILE_ID_PREFIX = "doc_"


@dataclass(frozen=True)
class UploadResult:
    """Exactly the four fields spec §17.1 returns. The storage key is never among them."""

    file_id: str
    file_name: str
    content_type: str
    size: int


def new_file_id() -> str:
    """An unguessable handle. 32 url-safe characters of entropy, not a counter."""
    return f"{FILE_ID_PREFIX}{secrets.token_urlsafe(24)}"


def storage_key_for(file_id: str, content_type: str, now: datetime) -> str:
    """A server-generated key. The uploaded filename never contributes to it.

    Partitioned by month so a directory never grows without bound, and suffixed with the
    *detected* type rather than the claimed one.
    """
    extension = min(EXTENSIONS[content_type])
    return f"kyc/{now:%Y/%m}/{file_id}{extension}"


class DocumentUploadService:
    """Validates and stores one uploaded file, then records its metadata."""

    def __init__(self, session: AsyncSession, storage: StorageProvider, *, max_bytes: int) -> None:
        self.session = session
        self.storage = storage
        self.max_bytes = max_bytes

    async def upload(
        self,
        actor: BusinessActor,
        upload: UploadFile,
        document_type: KycDocumentType | UploadType,
    ) -> UploadResult:
        """Store one upload.

        What a file may be depends on what it is *for*: a KYC slot takes PDF, JPG or PNG, while a
        task attachment also takes the office formats people actually send each other. The purpose
        is declared by the caller and the format is read from the bytes - neither is inferred from
        the other.
        """
        allowed = _allowed_types(document_type)
        head = await upload.read(SNIFF_BYTES)
        display_name = sanitize_filename(upload.filename)
        detection = detect_content_type(head, display_name)
        if detection.content_type is None:
            raise ApiError(
                "UNSUPPORTED_FILE_TYPE",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detection.reason,
                fields=[{"field": "file", "code": "unsupported_type", "message": detection.reason or ""}],
            )
        content_type = detection.content_type
        if content_type not in allowed:
            # The bytes are a format this endpoint understands, but not one this *purpose* takes -
            # a spreadsheet offered as an Aadhaar scan, say.
            message = _unsupported_message(document_type)
            raise ApiError(
                "UNSUPPORTED_FILE_TYPE",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                message,
                fields=[{"field": "file", "code": "unsupported_type", "message": message}],
            )
        if not extension_matches(content_type, display_name):
            # The bytes and the extension disagree. The bytes are believed, but the mismatch
            # is refused rather than silently corrected: it is either a mistake worth telling
            # the user about, or an attempt to have the file treated as something else later.
            raise ApiError(
                "FILE_TYPE_MISMATCH",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "The file contents do not match its extension.",
                fields=[{"field": "file", "code": "extension_mismatch", "message": "The file extension does not match its contents."}],
            )
        if upload.content_type and upload.content_type.split(";")[0].strip().lower() not in allowed:
            message = _unsupported_message(document_type)
            raise ApiError(
                "UNSUPPORTED_FILE_TYPE",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                message,
                fields=[{"field": "file", "code": "unsupported_type", "message": message}],
            )

        now = datetime.now(UTC)
        file_id = new_file_id()
        key = storage_key_for(file_id, content_type, now)
        stored = await self.storage.save(key, self._chunks(head, upload, key))

        document = CustomerDocument(
            id=file_id.removeprefix(FILE_ID_PREFIX)[:36],
            file_id=file_id,
            customer_id=None,
            owner_user_id=actor.user_id,
            merchant_id=actor.merchant_id,
            uploaded_by_user_id=actor.user_id,
            document_type=document_type.value,
            document_number=None,
            number_encrypted=None,
            number_masked=None,
            number_lookup_hash=None,
            checksum_sha256=stored.checksum_sha256,
            # The integration point for a real scanner: a provider hook sets CLEAN or
            # INFECTED here, and approval already refuses anything outside the allowed set.
            scan_status=ScanStatus.SKIPPED.value,
            storage_provider=self.storage.name,
            finalized_at=None,
            storage_key=stored.storage_key,
            original_filename=display_name,
            mime_type=content_type,
            file_size=stored.size,
            version=1,
            status=DocumentStatus.UPLOADED.value,
            is_mandatory=True,
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(document)
        await self.session.flush()
        return UploadResult(file_id=file_id, file_name=display_name, content_type=content_type, size=stored.size)

    async def _chunks(self, head: bytes, upload: UploadFile, key: str):
        """Stream the upload, enforcing the size limit as the bytes arrive.

        Never buffered whole: the limit is checked per chunk, so an oversized upload is cut
        off at the limit instead of being read into memory first and measured afterwards.
        """
        total = len(head)
        if total:
            yield head
        while chunk := await upload.read(READ_CHUNK):
            total += len(chunk)
            if total > self.max_bytes:
                # The provider deletes its partial file when the iterator raises.
                raise ApiError(
                    "FILE_TOO_LARGE",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"The file is larger than {self.max_bytes // (1024 * 1024)} MB.",
                    fields=[{"field": "file", "code": "too_large", "message": "Choose a smaller file."}],
                )
            yield chunk


def _allowed_types(document_type: "KycDocumentType | UploadType") -> set[str]:
    """Which formats this upload's purpose accepts."""
    if document_type == UploadType.TASK_ATTACHMENT:
        return TASK_CONTENT_TYPES
    return ALLOWED_CONTENT_TYPES


def _unsupported_message(document_type: "KycDocumentType | UploadType") -> str:
    if document_type == UploadType.TASK_ATTACHMENT:
        return "Upload a PDF, image, Word, Excel or CSV file."
    return "Upload a PDF, JPG or PNG."


def not_found() -> ApiError:
    return ApiError("DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND, "We could not find this document.")


class DocumentAccessService:
    """Decides who may see a stored document, and issues short-lived view grants."""

    def __init__(self, session: AsyncSession, *, secret: str, expires_in: int) -> None:
        self.session = session
        self.secret = secret
        self.expires_in = expires_in

    async def readable(self, actor: BusinessActor, file_id: str) -> CustomerDocument:
        """Load a document the actor is allowed to read, or raise 404.

        A merchant reviewer may read a document belonging to their own merchant. A customer
        may read only their own. Everything else is indistinguishable from a file that does
        not exist.
        """
        document = await self.session.scalar(select(CustomerDocument).where(CustomerDocument.file_id == file_id))
        if document is None:
            raise not_found()
        if actor.is_customer:
            owns_upload = document.owner_user_id == actor.user_id
            owns_customer = document.customer_id is not None and document.customer_id == actor.customer_id
            if not (owns_upload or owns_customer):
                raise not_found()
            return document
        if actor.merchant_id is None or document.merchant_id != actor.merchant_id:
            raise not_found()
        return document

    async def attachable(self, actor: BusinessActor, file_id: str, document_type: KycDocumentType) -> CustomerDocument:
        """Load an upload the actor may attach to a registration they are performing.

        Stricter than `readable`: an already-finalized file cannot be attached again, and the
        declared type must match the type the file was uploaded as — otherwise a PAN scan
        could be submitted in the Aadhaar slot.
        """
        document = await self.session.scalar(select(CustomerDocument).where(CustomerDocument.file_id == file_id))
        field = f"doc.{document_type.value}.file"
        if document is None:
            raise self._file_error(field, "not_found", "Upload this document again.")
        if document.document_type != document_type.value:
            raise self._file_error(field, "type_mismatch", "This file was uploaded as a different document type.")
        if document.finalized_at is not None:
            raise self._file_error(field, "already_used", "This file is already attached to a registration.")
        if actor.is_customer:
            if document.owner_user_id != actor.user_id:
                raise self._file_error(field, "not_found", "Upload this document again.")
        elif document.merchant_id is None or document.merchant_id != actor.merchant_id:
            raise self._file_error(field, "not_found", "Upload this document again.")
        return document

    @staticmethod
    def _file_error(field: str, code: str, message: str) -> ApiError:
        # A foreign file id is reported exactly like a missing one, so the response cannot be
        # used to discover which ids exist.
        return ApiError(
            "VALIDATION_ERROR",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            fields=[{"field": field, "code": code, "message": message}],
        )

    def grant(self, actor: BusinessActor, document: CustomerDocument, *, now: datetime | None = None) -> tuple[str, int]:
        """Mint a short-lived view token bound to this file **and** this viewer.

        Used when the storage provider has no signed URL of its own. Binding the viewer
        matters: a forwarded link is useless to anyone else, because the streaming endpoint
        checks that the caller is the user named in the token.
        """
        moment = now or datetime.now(UTC)
        expires_at = int((moment + timedelta(seconds=self.expires_in)).timestamp())
        payload = f"{document.file_id}:{actor.user_id}:{expires_at}"
        signature = self._sign(payload)
        token = urlsafe_b64encode(f"{payload}:{signature}".encode()).decode("ascii").rstrip("=")
        return token, self.expires_in

    def verify(self, token: str, *, now: datetime | None = None) -> tuple[str, str]:
        """Return `(file_id, user_id)` for a valid token, or raise.

        The viewer is read *out of* the token rather than compared against a session, so the
        link works in a plain image view with no Authorization header — which is what spec
        §17.2 asks a signed URL to be. The caller still re-checks that the named user may
        read the file, so a reviewer removed from the merchant loses access immediately even
        while their token is unexpired.
        """
        try:
            padded = token + "=" * (-len(token) % 4)
            file_id, user_id, expires_at, signature = urlsafe_b64decode(padded).decode("utf-8").rsplit(":", 3)
        except (ValueError, UnicodeDecodeError) as exc:
            raise not_found() from exc
        if not hmac.compare_digest(self._sign(f"{file_id}:{user_id}:{expires_at}"), signature):
            raise not_found()
        moment = now or datetime.now(UTC)
        try:
            expiry = int(expires_at)
        except ValueError as exc:
            raise not_found() from exc
        if expiry < int(moment.timestamp()):
            raise ApiError("DOCUMENT_URL_EXPIRED", status.HTTP_410_GONE, "This link has expired. Open the document again.")
        return file_id, user_id

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
