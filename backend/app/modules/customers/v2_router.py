"""Customer registration endpoints mounted only below ``/api/v2/customer``."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.account_state import CUSTOMER_PROFILE_INCOMPLETE
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.business_catalogue.service import BusinessCatalogueService
from app.modules.customers.business_schemas import Address, CustomerRegistrationRequest
from app.modules.customers.dependencies import AccessDep, OnboardingActorDep, RegistrationDep
from app.modules.customers.models import CustomerProfile
from app.modules.customers.router import (
    DOCUMENT_FORMAT_HINTS,
    EDITABLE_STATUSES,
    _active_merchant,
    _onboarding_user,
    _own_profile,
    _response,
    _status_response,
)
from app.modules.customers.schemas import CustomerProfileResponse, RegistrationStatusResponse
from app.modules.customers.v2_schemas import (
    CustomerProfileV2Payload,
    CustomerProfileV2Update,
    DocumentSide,
    KycDocumentRequirementV2,
    KycRequirementsResponseV2,
)
from app.modules.customers.v2_service import CustomerRegistrationV2Service
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_onboarding_user
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter()


def _business_request(
    payload,
    profile: CustomerProfile,
    *,
    default_customer_type: str = "RETAIL",
) -> CustomerRegistrationRequest:
    customer_type = payload.customer_type if payload.customer_type else profile.customer_type
    address = payload.delivery_address or Address(
        line1=profile.address_line1 or "",
        line2=profile.address_line2,
        city=profile.address_city or "",
        state=profile.address_state or "",
        pincode=profile.address_pincode or "",
    )
    return CustomerRegistrationRequest(
        customer_type=customer_type or default_customer_type,
        business_name=payload.business_name or payload.name or profile.name or "",
        owner_name=payload.owner_name or profile.owner_name or "",
        mobile=payload.mobile,
        email=payload.email if payload.email is not None else profile.email,
        delivery_address=address,
        documents=[],
        sites=payload.sites or [],
    )


def get_v2_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    base: RegistrationDep,
    access: AccessDep,
) -> CustomerRegistrationV2Service:
    return CustomerRegistrationV2Service(session, base=base, access=access)


V2ServiceDep = Annotated[CustomerRegistrationV2Service, Depends(get_v2_service)]


@router.get("/registration/kyc-requirements", response_model=KycRequirementsResponseV2)
async def kyc_requirements_v2(
    customer_type: Annotated[str, Query(alias="customerType", min_length=1, max_length=40)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KycRequirementsResponseV2:
    customer_type_code = customer_type.strip().upper()
    requirements = await BusinessCatalogueService(session).active_kyc_requirements(
        customer_type_code
    )
    required_count = sum(1 for rule, _ in requirements if rule.requirement_mode == "REQUIRED")
    groups: dict[str, int] = {}
    for rule, _ in requirements:
        if rule.requirement_mode == "ANY_OF" and rule.requirement_group:
            groups[rule.requirement_group] = max(
                groups.get(rule.requirement_group, 0), rule.min_required
            )
    return KycRequirementsResponseV2(
        customer_type=customer_type_code,
        minimum_documents=required_count + sum(groups.values()),
        documents=[
            KycDocumentRequirementV2(
                type=document.code,
                label=document.label,
                required=rule.requirement_mode == "REQUIRED",
                required_group=rule.requirement_group
                if rule.requirement_mode == "ANY_OF"
                else None,
                number_format=DOCUMENT_FORMAT_HINTS.get(
                    document.code, document.number_pattern or "Configured by administrator"
                ),
                allowed_sides=[DocumentSide.FRONT, DocumentSide.BACK],
                allowed_mime_types=["image/jpeg", "image/png", "application/pdf"],
                max_size_bytes=settings.document_max_bytes,
            )
            for rule, document in requirements
        ],
    )


async def _save_v2_profile(profile, payload, user, actor, service, session) -> None:
    default_type = (await BusinessCatalogueService(session).default_customer_type()).code
    request = _business_request(payload, profile, default_customer_type=default_type)
    profile.customer_type = request.customer_type
    prepared = await service.prepare(profile, actor, payload.documents or [], request.customer_type)
    await service.save(profile, request, actor, prepared, verified_mobile=user.mobile_number)


@router.post(
    "/registration/profile",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_registration_profile_v2(
    payload: CustomerProfileV2Payload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    service: V2ServiceDep,
) -> CustomerProfileResponse:
    user = await _onboarding_user(session, context)
    if payload.mobile_number is not None and normalize_mobile_number(payload.mobile_number) != user.mobile_number:
        raise ApiError("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN, "The mobile number does not match the verified number.")
    if await _own_profile(session, user) is not None:
        raise ApiError("REGISTRATION_PROFILE_EXISTS", status.HTTP_409_CONFLICT)
    merchant = await _active_merchant(session, payload.merchant_code)
    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()), user_id=user.id, merchant_id=merchant.id, merchant_code=merchant.code,
        customer_type=payload.customer_type or None,
        mobile_number=user.mobile_number, name=payload.name, gst_number=payload.gst_number,
        status=CUSTOMER_PROFILE_INCOMPLETE, rejection_reason=None, mobile_verified_at=now,
        submitted_at=None, reviewed_by=None, reviewed_at=None, created_at=now, updated_at=now,
    )
    session.add(profile)
    await session.flush()
    await _save_v2_profile(profile, payload, user, actor, service, session)
    await session.commit()
    return _response(profile)
    await session.commit()
    return _response(profile)


@router.get("/registration/profile", response_model=CustomerProfileResponse, responses=error_responses(401, 403, 404))
async def get_registration_profile_v2(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
) -> CustomerProfileResponse:
    profile = await _own_profile(session, await _onboarding_user(session, context))
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return _response(profile)


@router.patch("/registration/profile", response_model=CustomerProfileResponse, responses=error_responses(401, 403, 404, 409, 422))
async def update_registration_profile_v2(
    payload: CustomerProfileV2Update,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    service: V2ServiceDep,
) -> CustomerProfileResponse:
    user = await _onboarding_user(session, context)
    profile = await _own_profile(session, user, lock=True)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if profile.status not in EDITABLE_STATUSES:
        raise ApiError("REGISTRATION_NOT_EDITABLE", status.HTTP_409_CONFLICT)
    if payload.merchant_code:
        merchant = await _active_merchant(session, payload.merchant_code)
        profile.merchant_id, profile.merchant_code = merchant.id, merchant.code
    if payload.customer_type is not None:
        profile.customer_type = payload.customer_type
    if payload.name is not None:
        profile.name = payload.name
    if payload.gst_number is not None:
        profile.gst_number = payload.gst_number
    await _save_v2_profile(profile, payload, user, actor, service, session)
    profile.updated_at = datetime.now(UTC)
    await session.commit()
    return _response(profile)


@router.post("/registration/submit", response_model=RegistrationStatusResponse, responses=error_responses(401, 403, 404, 409, 422))
async def submit_registration_v2(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    base: RegistrationDep,
) -> RegistrationStatusResponse:
    user = await _onboarding_user(session, context)
    profile = await _own_profile(session, user, lock=True)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if profile.merchant_code:
        merchant = await _active_merchant(session, profile.merchant_code)
        profile.merchant_id = merchant.id
    await base.submit_self_registration(profile, actor)
    await session.commit()
    return await _status_response(session, user, base)


@router.get("/registration/status", response_model=RegistrationStatusResponse, responses=error_responses(401, 403))
async def registration_status_v2(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    base: RegistrationDep,
) -> RegistrationStatusResponse:
    return await _status_response(session, await _onboarding_user(session, context), base)
