from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.account_state import (
    CUSTOMER_APPROVED,
    CUSTOMER_DOCUMENTS_PENDING,
    CUSTOMER_PROFILE_INCOMPLETE,
    CUSTOMER_REJECTED,
    CUSTOMER_UNDER_REVIEW,
    AccountStateResolver,
)
from app.modules.authentication.audit import ClientInfo
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.dependencies import get_client_info
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.throttle import RequestThrottle
from app.modules.customers.business_schemas import (
    Address,
    CustomerRegistrationRequest,
    RegistrationProgressResponse,
)
from app.modules.customers.constants import CustomerType as BusinessCustomerType
from app.modules.customers.constants import to_mobile_account_status
from app.modules.customers.dependencies import OnboardingActorDep, RegistrationDep
from app.modules.customers.models import CustomerProfile, KycApplication
from app.modules.customers.schemas import (
    CheckMobileRequest,
    CheckMobileResponse,
    CustomerProfilePayload,
    CustomerProfileResponse,
    CustomerProfileUpdate,
    CustomerType,
    RegistrationField,
    RegistrationFieldsResponse,
    RegistrationStatusResponse,
)
from app.modules.merchants.models import Merchant
from app.modules.users.models import User
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_onboarding_user
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter()

EDITABLE_STATUSES = {CUSTOMER_PROFILE_INCOMPLETE, CUSTOMER_DOCUMENTS_PENDING, CUSTOMER_REJECTED}
STATUS_MESSAGES = {
    "NOT_STARTED": "Registration details have not been submitted.",
    CUSTOMER_PROFILE_INCOMPLETE: "Complete your registration details and submit them for review.",
    CUSTOMER_DOCUMENTS_PENDING: "Upload the required documents.",
    CUSTOMER_UNDER_REVIEW: "Your registration is being reviewed.",
    CUSTOMER_APPROVED: "Your registration is approved. Sign in to continue.",
    CUSTOMER_REJECTED: "Your registration was rejected. Update your details and submit again.",
    "SUSPENDED": "Your account is suspended. Contact support.",
}


@router.post("/auth/check-mobile", response_model=CheckMobileResponse, responses=error_responses(422, 429))
async def check_mobile(
    payload: CheckMobileRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[ClientInfo, Depends(get_client_info)],
) -> CheckMobileResponse:
    mobile = normalize_mobile_number(payload.mobile_number)
    # This endpoint reveals whether a customer registration exists, so it is limited per client IP.
    try:
        await RequestThrottle(session, settings.jwt_signing_secret).hit("check_mobile:ip", client.ip_address, settings.check_mobile_limit_per_ip)
    finally:
        await session.commit()
    existing = await session.scalar(select(CustomerProfile.id).where(CustomerProfile.mobile_number == mobile))
    if existing is None:
        return CheckMobileResponse(
            code="NUMBER_NOT_REGISTERED",
            message="Mobile number is not registered. Registration may be started.",
            registered=False,
            registration_allowed=True,
        )
    return CheckMobileResponse(code="MOBILE_REGISTERED", message="Mobile number is registered.", registered=True)


@router.get("/registration/fields", response_model=RegistrationFieldsResponse)
async def registration_fields() -> RegistrationFieldsResponse:
    return RegistrationFieldsResponse(
        fields=[
            RegistrationField(
                api_field_name="mobile_number",
                display_label="Mobile Number",
                data_type="string",
                required=True,
                source="Customer App sheet",
                required_for="create",
            ),
            RegistrationField(
                api_field_name="customer_type",
                display_label="Customer Type",
                data_type="enum",
                required=True,
                source="Customer App sheet",
                allowed_values=[item.value for item in CustomerType],
            ),
            RegistrationField(
                api_field_name="merchant_code",
                display_label="Merchant Code",
                data_type="string",
                required=True,
                source="SYSTEM_REQUIRED_NEEDS_REVIEW",
                required_for="create",
            ),
            RegistrationField(
                api_field_name="name",
                display_label="Customer Name",
                data_type="string",
                required=True,
                source="SRS/SOW Customer Management",
            ),
            RegistrationField(
                api_field_name="gst_number",
                display_label="GST Number",
                data_type="string",
                required=False,
                source="SRS/SOW Customer Management",
            ),
        ]
    )



# Spec fields are optional on the onboarding payload; when none are present the request is a
# legacy draft save and the shared registration service is not involved at all.
SPEC_FIELDS = ("owner_name", "email", "delivery_address", "documents", "sites", "business_name")


def _has_spec_fields(updates: dict) -> bool:
    return any(field in updates for field in SPEC_FIELDS)


def _registration_request(payload, profile: CustomerProfile) -> CustomerRegistrationRequest:
    """Build the shared registration body from an onboarding payload plus what is stored.

    Merging with the stored row is what makes a partial save work: the app can send the
    address on one call and the documents on the next without the first being wiped.
    """
    customer_type = payload.customer_type.value if payload.customer_type else profile.customer_type
    address = payload.delivery_address or Address(
        line1=profile.address_line1 or "",
        line2=profile.address_line2,
        city=profile.address_city or "",
        state=profile.address_state or "",
        pincode=profile.address_pincode or "",
    )
    return CustomerRegistrationRequest(
        customer_type=BusinessCustomerType(customer_type or BusinessCustomerType.RETAIL.value),
        business_name=payload.business_name or payload.name or profile.name or "",
        owner_name=payload.owner_name or profile.owner_name or "",
        mobile=payload.mobile,
        email=payload.email if payload.email is not None else profile.email,
        delivery_address=address,
        documents=payload.documents or [],
        sites=payload.sites or [],
    )


async def _onboarding_user(session: AsyncSession, context: AuthContext) -> User:
    user = await session.get(User, context.user_id)
    if user is None or not user.mobile_number:
        raise ApiError("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
    return user


async def _own_profile(session: AsyncSession, user: User, *, lock: bool = False) -> CustomerProfile | None:
    statement = select(CustomerProfile).where(
        (CustomerProfile.user_id == user.id) | (CustomerProfile.mobile_number == user.mobile_number)
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def _active_merchant(session: AsyncSession, merchant_code: str) -> Merchant:
    merchant = await session.scalar(select(Merchant).where(Merchant.code == merchant_code))
    if merchant is None or merchant.status != "ACTIVE" or merchant.approval_status != "APPROVED":
        raise ApiError(
            "MERCHANT_CODE_INVALID",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            fields=[{"field": "merchant_code", "code": "merchant_code_invalid", "message": "The merchant code is not valid."}],
        )
    return merchant


def _response(profile: CustomerProfile) -> CustomerProfileResponse:
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


@router.post(
    "/registration/profile",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_registration_profile(
    payload: CustomerProfilePayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    service: RegistrationDep,
) -> CustomerProfileResponse:
    user = await _onboarding_user(session, context)
    if payload.mobile_number is not None and normalize_mobile_number(payload.mobile_number) != user.mobile_number:
        raise ApiError("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN, "The mobile number does not match the verified number.")
    if await _own_profile(session, user) is not None:
        raise ApiError("REGISTRATION_PROFILE_EXISTS", status.HTTP_409_CONFLICT)
    merchant = await _active_merchant(session, payload.merchant_code)
    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()),
        user_id=user.id,
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        customer_type=payload.customer_type.value if payload.customer_type else None,
        mobile_number=user.mobile_number,
        name=payload.name,
        gst_number=payload.gst_number,
        status=CUSTOMER_PROFILE_INCOMPLETE,
        rejection_reason=None,
        mobile_verified_at=now,
        submitted_at=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    if _has_spec_fields(payload.model_dump(exclude_unset=True)):
        # The full API_SPEC contract was sent. It goes through the same service the merchant
        # create path uses, so both actors get identical validation.
        await session.flush()
        await service.save_self_profile(profile, _registration_request(payload, profile), actor, verified_mobile=user.mobile_number)
    try:
        await session.commit()
    except IntegrityError as exc:
        # A concurrent request created the profile first.
        await session.rollback()
        raise ApiError("REGISTRATION_PROFILE_EXISTS", status.HTTP_409_CONFLICT) from exc
    return _response(profile)


@router.get("/registration/profile", response_model=CustomerProfileResponse, responses=error_responses(401, 403, 404))
async def get_registration_profile(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
) -> CustomerProfileResponse:
    profile = await _own_profile(session, await _onboarding_user(session, context))
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return _response(profile)


@router.patch("/registration/profile", response_model=CustomerProfileResponse, responses=error_responses(401, 403, 404, 409, 422))
async def update_registration_profile(
    payload: CustomerProfileUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    service: RegistrationDep,
) -> CustomerProfileResponse:
    user = await _onboarding_user(session, context)
    profile = await _own_profile(session, user, lock=True)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if profile.status not in EDITABLE_STATUSES:
        raise ApiError("REGISTRATION_NOT_EDITABLE", status.HTTP_409_CONFLICT)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("merchant_code"):
        merchant = await _active_merchant(session, updates["merchant_code"])
        profile.merchant_id, profile.merchant_code = merchant.id, merchant.code
    if "customer_type" in updates:
        profile.customer_type = updates["customer_type"].value if updates["customer_type"] else None
    for field in ("name", "gst_number"):
        if field in updates:
            setattr(profile, field, updates[field])
    if _has_spec_fields(updates):
        await service.save_self_profile(profile, _registration_request(payload, profile), actor, verified_mobile=user.mobile_number)
    profile.updated_at = datetime.now(UTC)
    await session.commit()
    return _response(profile)


@router.post("/registration/submit", response_model=RegistrationStatusResponse, responses=error_responses(401, 403, 404, 409, 422))
async def submit_registration(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    actor: OnboardingActorDep,
    service: RegistrationDep,
) -> RegistrationStatusResponse:
    """Submit the saved registration for merchant review.

    Idempotent: submitting again while the registration is already under review returns the
    current status and does not open a second application.
    """
    user = await _onboarding_user(session, context)
    profile = await _own_profile(session, user, lock=True)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    # Re-resolve the merchant at submit time: a merchant deactivated since the draft was
    # saved must not receive new applications.
    if profile.merchant_code:
        merchant = await _active_merchant(session, profile.merchant_code)
        profile.merchant_id = merchant.id
    await service.submit_self_registration(profile, actor)
    await session.commit()
    return await _status_response(session, user, service)


@router.get("/registration/status", response_model=RegistrationStatusResponse, responses=error_responses(401, 403))
async def registration_status(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
    service: RegistrationDep,
) -> RegistrationStatusResponse:
    return await _status_response(session, await _onboarding_user(session, context), service)


async def _status_response(session: AsyncSession, user: User, service=None) -> RegistrationStatusResponse:
    state = await AccountStateResolver(session).resolve(user, LoginChannel.CUSTOMER)
    profile_state = state.customer_profile
    status_value = profile_state["status"] if profile_state else "NOT_STARTED"
    return RegistrationStatusResponse(
        status=status_value,
        message=STATUS_MESSAGES.get(status_value, "Registration status loaded."),
        next_action=state.next_action_for("onboarding"),
        rejection_reason=profile_state["rejection_reason"] if profile_state else None,
        progress=await _progress(session, user, service),
    )


async def _progress(session: AsyncSession, user: User, service) -> RegistrationProgressResponse | None:
    """The extra detail the Application Status screen renders.

    Returned alongside the existing fields rather than replacing them, so the shipped app -
    which reads `status`, `message`, `next_action` and `rejection_reason` - is unaffected.
    """
    profile = await _own_profile(session, user)
    if profile is None or service is None:
        return None
    application = await session.scalar(
        select(KycApplication)
        .where(KycApplication.customer_id == profile.id)
        .order_by(KycApplication.submitted_at.desc())
        .limit(1)
    )
    missing_fields, missing_documents = await service.missing_for_submit(profile)
    return RegistrationProgressResponse(
        customer_id=profile.id,
        code=profile.code,
        customer_type=profile.customer_type,
        account_status=to_mobile_account_status(profile.status),
        kyc_status=profile.kyc_status,
        profile_complete=not missing_fields and not missing_documents,
        application_id=application.id if application else None,
        application_status=application.status if application else None,
        submitted_at=application.submitted_at if application else profile.submitted_at,
        reviewed_at=application.reviewed_at if application else profile.reviewed_at,
        rejection_reason=profile.rejection_reason,
        missing_fields=missing_fields,
        missing_documents=missing_documents,
    )
