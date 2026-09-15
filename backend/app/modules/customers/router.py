from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.customers.models import CustomerProfile
from app.modules.customers.schemas import (
    CheckMobileRequest,
    CheckMobileResponse,
    CustomerProfilePayload,
    CustomerProfileResponse,
    RegistrationField,
    RegistrationFieldsResponse,
    RegistrationStatusResponse,
)
from app.shared.database.session import get_db_session

router = APIRouter()


@router.post("/auth/check-mobile", response_model=CheckMobileResponse)
async def check_mobile(
    payload: CheckMobileRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckMobileResponse:
    mobile = normalize_mobile_number(payload.mobile_number)
    existing = await session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))
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
            ),
            RegistrationField(
                api_field_name="customer_type",
                display_label="Customer Type",
                data_type="enum",
                required=True,
                source="Customer App sheet",
            ),
            RegistrationField(
                api_field_name="merchant_code",
                display_label="Merchant Code",
                data_type="string",
                required=True,
                source="SYSTEM_REQUIRED_NEEDS_REVIEW",
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


@router.post("/registration/profile", response_model=CustomerProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_registration_profile(
    payload: CustomerProfilePayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerProfileResponse:
    mobile = normalize_mobile_number(payload.mobile_number)
    if not payload.merchant_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="merchant_code is required pending source review")
    existing = await session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration profile already exists")
    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()),
        user_id=None,
        merchant_id=None,
        merchant_code=payload.merchant_code,
        customer_type=payload.customer_type,
        mobile_number=mobile,
        name=payload.name,
        gst_number=payload.gst_number,
        status="PROFILE_INCOMPLETE",
        rejection_reason=None,
        mobile_verified_at=None,
        submitted_at=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


@router.get("/registration/status", response_model=RegistrationStatusResponse)
async def registration_status(mobile_number: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> RegistrationStatusResponse:
    mobile = normalize_mobile_number(mobile_number)
    profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))
    if profile is None:
        return RegistrationStatusResponse(status="DRAFT", message="Registration profile has not been created.")
    return RegistrationStatusResponse(status=profile.status, message="Registration status loaded.")
