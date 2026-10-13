"""Resolve a Super Admin/Admin request into one explicit merchant business scope.

Admin APIs that reuse merchant business services must never infer a tenant and must never run
unscoped.  The selected merchant therefore comes from one required ``merchantId`` query
parameter, while the acting user and audit identity continue to come from the validated Admin
session.
"""

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.merchants.models import Merchant
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user
from app.shared.authorization.exceptions import AuthorizationDeniedError
from app.shared.business.actor import BusinessActor, BusinessActorResolver
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError


async def get_admin_merchant_actor(
    merchant_id: Annotated[
        str,
        Query(
            alias="merchantId",
            min_length=1,
            max_length=36,
            description="Required merchant scope for this Admin operation.",
        ),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> BusinessActor:
    if context.login_channel is not LoginChannel.ADMIN:
        raise AuthorizationDeniedError("CHANNEL_NOT_ALLOWED")

    merchant = await session.get(Merchant, merchant_id)
    if merchant is None:
        raise ApiError(
            "MERCHANT_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "The selected merchant does not exist.",
        )

    admin = await BusinessActorResolver(session).resolve(context)
    return replace(
        admin,
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        staff_type="PLATFORM_ADMIN",
    )


AdminMerchantActorDep = Annotated[BusinessActor, Depends(get_admin_merchant_actor)]
