"""FastAPI dependencies for the customer and KYC routes.

Everything here builds *on top of* the frozen authentication dependencies. No route in this
slice validates a token, reads a claim or touches a session; they take the `AuthContext` the
auth layer already produced and turn it into the business objects they need.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.audit import ClientInfo
from app.modules.authentication.constants import LoginChannel, SessionType
from app.modules.authentication.dependencies import get_client_info
from app.modules.authentication.session_service import SessionService
from app.modules.customers.documents import DocumentAccessService, DocumentUploadService
from app.modules.customers.registration import CustomerRegistrationService
from app.modules.customers.review import KycReviewService
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    bearer_scheme,
    require_authenticated_user,
    require_onboarding_user,
)
from app.shared.business.actor import BusinessActor, BusinessActorResolver
from app.shared.business.audit import BusinessAuditor
from app.shared.crypto import FieldCipher
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.storage import LocalStorageProvider, StorageProvider

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@lru_cache(maxsize=4)
def _storage(provider: str, root: str) -> StorageProvider:
    """One provider instance per configuration.

    Cached because constructing the local provider creates its root directory; doing that on
    every request would stat the filesystem needlessly.
    """
    if provider == "local":
        return LocalStorageProvider(root)
    raise RuntimeError(
        f"DOCUMENT_STORAGE_PROVIDER={provider!r} is not implemented. "
        "Bind a StorageProvider for it, or use 'local' where that is approved."
    )


def get_storage(settings: SettingsDep) -> StorageProvider:
    """Resolve the storage provider, refusing an unsafe production configuration.

    Checked here rather than in `Settings` so a deployment that does not use documents yet
    still boots; the refusal lands on the first document request instead, which is the first
    moment the configuration actually matters.
    """
    if (
        settings.document_storage_provider == "local"
        and not settings.is_local_environment
        and not settings.allow_local_document_storage_in_production
    ):
        raise ApiError(
            "SERVICE_UNAVAILABLE",
            503,
            "Document storage is not configured for this environment.",
        )
    return _storage(settings.document_storage_provider, settings.document_storage_root)


@lru_cache(maxsize=4)
def _cipher(secret: str) -> FieldCipher:
    return FieldCipher(secret)


def get_document_cipher(settings: SettingsDep) -> FieldCipher:
    return _cipher(settings.document_cipher_secret)


async def get_business_actor(
    session: SessionDep,
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> BusinessActor:
    """The actor for a full app session (customer or merchant staff)."""
    return await BusinessActorResolver(session).resolve(context)


async def get_onboarding_actor(
    session: SessionDep,
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
) -> BusinessActor:
    """The actor for a customer still completing registration.

    Their user row is `PENDING`, which the standard resolver refuses, so the actor is built
    directly from the already-validated onboarding context. The auth layer has still done
    every check: this only skips the *business* rule that an actor must be an active account,
    which is precisely what an onboarding session is not yet.
    """
    from sqlalchemy import select

    from app.modules.customers.models import CustomerProfile
    from app.modules.users.models import User
    from app.shared.exceptions.api_error import ApiError

    user = await session.get(User, context.user_id)
    if user is None or not user.mobile_number:
        raise ApiError("SESSION_REVOKED", 401)
    profile = await session.scalar(
        select(CustomerProfile).where(
            (CustomerProfile.user_id == user.id) | (CustomerProfile.mobile_number == user.mobile_number)
        )
    )
    return BusinessActor(
        user_id=user.id,
        login_channel=context.login_channel,
        display_name=user.full_name or "Customer",
        session_id=context.session_id,
        customer_id=profile.id if profile else None,
        merchant_id=profile.merchant_id if profile else None,
        merchant_code=profile.merchant_code if profile else None,
    )


def get_auditor(
    session: SessionDep,
    settings: SettingsDep,
    client: Annotated[ClientInfo, Depends(get_client_info)],
) -> BusinessAuditor:
    return BusinessAuditor(session, store_ip=settings.auth_audit_store_ip, ip_address=client.ip_address)


def get_document_access(session: SessionDep, settings: SettingsDep) -> DocumentAccessService:
    return DocumentAccessService(
        session,
        secret=settings.jwt_signing_secret,
        expires_in=settings.document_url_expires_seconds,
    )


def get_document_upload(
    session: SessionDep,
    settings: SettingsDep,
    storage: Annotated[StorageProvider, Depends(get_storage)],
) -> DocumentUploadService:
    return DocumentUploadService(session, storage, max_bytes=settings.document_max_bytes)


def get_registration_service(
    session: SessionDep,
    cipher: Annotated[FieldCipher, Depends(get_document_cipher)],
    documents: Annotated[DocumentAccessService, Depends(get_document_access)],
    auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
) -> CustomerRegistrationService:
    return CustomerRegistrationService(session, cipher=cipher, documents=documents, auditor=auditor)


def get_review_service(
    session: SessionDep,
    settings: SettingsDep,
    auditor: Annotated[BusinessAuditor, Depends(get_auditor)],
) -> KycReviewService:
    return KycReviewService(
        session,
        auditor=auditor,
        allow_skipped_scan=settings.is_local_environment and settings.allow_skipped_kyc_scan_in_local,
    )


ActorDep = Annotated[BusinessActor, Depends(get_business_actor)]
OnboardingActorDep = Annotated[BusinessActor, Depends(get_onboarding_actor)]
UploadDep = Annotated[DocumentUploadService, Depends(get_document_upload)]
AccessDep = Annotated[DocumentAccessService, Depends(get_document_access)]
RegistrationDep = Annotated[CustomerRegistrationService, Depends(get_registration_service)]
ReviewDep = Annotated[KycReviewService, Depends(get_review_service)]
StorageDep = Annotated[StorageProvider, Depends(get_storage)]


async def require_customer_session(
    credentials: Annotated[object, Depends(bearer_scheme)] = None,
    settings: SettingsDep = None,
    session: SessionDep = None,
) -> AuthContext:
    """Accept either customer session type, using the existing session validator.

    Nothing about token validation changes: `SessionService.validate_access_token` is the
    same frozen call the authentication dependencies make. Only the set of session types this
    particular route family admits is different, and it stays locked to the customer channel.
    """
    validated = await SessionService(session, settings).validate_access_token(
        credentials.credentials if credentials else None,
        allowed_types=frozenset({SessionType.ACCESS.value, SessionType.ONBOARDING.value}),
        channel=LoginChannel.CUSTOMER,
    )
    return AuthContext(
        user_id=validated.user.id,
        login_channel=validated.channel,
        session_id=validated.session.id,
        token_type=validated.token_type,
    )


async def get_customer_actor(
    session: SessionDep,
    context: Annotated[AuthContext, Depends(require_customer_session)],
) -> BusinessActor:
    """Actor for a customer holding *either* session type.

    Documents are uploaded during onboarding and viewed again afterwards, so both the
    onboarding session and the full customer session have to reach these routes. The auth
    layer still validates the token; this only widens which of its own session types the
    route accepts, and only for the customer channel.
    """
    if context.token_type == SessionType.ONBOARDING.value:
        return await get_onboarding_actor(session, context)
    return await BusinessActorResolver(session).resolve(context)


CustomerActorDep = Annotated[BusinessActor, Depends(get_customer_actor)]
