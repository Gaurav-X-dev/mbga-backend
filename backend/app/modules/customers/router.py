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
from app.modules.customers.models import CustomerProfile
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
) -> CustomerProfileResponse:
    profile = await _own_profile(session, await _onboarding_user(session, context), lock=True)
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
    profile.updated_at = datetime.now(UTC)
    await session.commit()
    return _response(profile)


@router.post("/registration/submit", response_model=RegistrationStatusResponse, responses=error_responses(401, 403, 404, 409, 422))
async def submit_registration(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
) -> RegistrationStatusResponse:
    user = await _onboarding_user(session, context)
    profile = await _own_profile(session, user, lock=True)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if profile.status == CUSTOMER_UNDER_REVIEW:
        return await _status_response(session, user)
    if profile.status not in EDITABLE_STATUSES:
        raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT)
    missing = [
        {"field": field, "code": "missing", "message": "This field is required before submitting."}
        for field in ("name", "customer_type", "merchant_code")
        if not getattr(profile, field)
    ]
    if missing:
        raise ApiError("REGISTRATION_INCOMPLETE", status.HTTP_422_UNPROCESSABLE_CONTENT, fields=missing)
    merchant = await _active_merchant(session, profile.merchant_code)
    now = datetime.now(UTC)
    profile.merchant_id = merchant.id
    profile.status = CUSTOMER_UNDER_REVIEW
    profile.rejection_reason = None
    profile.submitted_at = now
    profile.updated_at = now
    await session.commit()
    return await _status_response(session, user)


@router.get("/registration/status", response_model=RegistrationStatusResponse, responses=error_responses(401, 403))
async def registration_status(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_onboarding_user)],
) -> RegistrationStatusResponse:
    return await _status_response(session, await _onboarding_user(session, context))


async def _status_response(session: AsyncSession, user: User) -> RegistrationStatusResponse:
    state = await AccountStateResolver(session).resolve(user, LoginChannel.CUSTOMER)
    profile = state.customer_profile
    status_value = profile["status"] if profile else "NOT_STARTED"
    return RegistrationStatusResponse(
        status=status_value,
        message=STATUS_MESSAGES.get(status_value, "Registration status loaded."),
        next_action=state.next_action_for("onboarding"),
        rejection_reason=profile["rejection_reason"] if profile else None,
    )
