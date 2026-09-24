"""The customer's own profile (spec §5.2, `customerService.getMyProfile`).

Path is `/api/v1/customer/profile`. It is deliberately not `/api/v1/customer/auth/me`,
which belongs to the frozen authentication contract and returns a session, not a business
profile.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.business_schemas import CustomerResponse
from app.modules.customers.dependencies import CustomerActorDep
from app.modules.customers.mapping import CustomerViewLoader
from app.modules.customers.models import CustomerProfile
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/profile", tags=["Customer Profile"])
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get(
    "",
    response_model=CustomerResponse,
    responses=error_responses(401, 403, 404),
    summary="My customer profile",
)
async def my_profile(actor: CustomerActorDep, session: SessionDep) -> CustomerResponse:
    """The signed-in customer's own record.

    `404` while the customer has not registered yet, which is what the app routes on to show
    the registration flow instead of the profile screen.
    """
    if actor.customer_id is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    profile = await session.get(CustomerProfile, actor.customer_id)
    if profile is None:
        raise ApiError("REGISTRATION_PROFILE_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return await CustomerViewLoader(session).customer_view(profile)
