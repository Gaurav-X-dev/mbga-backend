"""Merchant V2 customer creation with up to two images per KYC document."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import AccessDep, ActorDep, RegistrationDep
from app.modules.customers.merchant_v2_schemas import (
    MerchantCustomerRegistrationRequestV2,
    MerchantCustomerResponseV2,
)
from app.modules.customers.merchant_v2_service import MerchantKycV2Service
from app.modules.customers.v2_service import CustomerRegistrationV2Service
from app.modules.merchants.models import Merchant
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/customers", tags=["Merchant V2 Customers"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
CREATE_CUSTOMER = Depends(require_permission("customers.create"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_merchant_registration_v2_service(
    session: SessionDep,
    base: RegistrationDep,
    access: AccessDep,
) -> CustomerRegistrationV2Service:
    return CustomerRegistrationV2Service(session, base=base, access=access)


RegistrationV2Dep = Annotated[
    CustomerRegistrationV2Service,
    Depends(get_merchant_registration_v2_service),
]


@router.post(
    "",
    response_model=MerchantCustomerResponseV2,
    status_code=status.HTTP_201_CREATED,
    dependencies=[MERCHANT_ONLY, CREATE_CUSTOMER],
    responses=error_responses(401, 403, 409, 422),
    summary="Add a customer with V2 multi-image KYC documents",
)
async def create_customer_v2(
    payload: MerchantCustomerRegistrationRequestV2,
    actor: ActorDep,
    service: RegistrationV2Dep,
    session: SessionDep,
) -> MerchantCustomerResponseV2:
    merchant = await session.get(Merchant, actor.require_merchant_id())
    if merchant is None:
        raise ApiError("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN)
    profile, _application = await service.create_customer_by_merchant(
        payload, actor, merchant
    )
    await session.commit()
    await session.refresh(profile)
    return await MerchantKycV2Service(session).customer(profile)
