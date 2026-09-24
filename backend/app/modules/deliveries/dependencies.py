from typing import Annotated

from fastapi import Depends

from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user
from app.shared.authorization.exceptions import AuthorizationDeniedError


async def require_delivery_user(
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> AuthContext:
    """Restrict Driver App resources to sessions issued for the DELIVERY channel."""
    if context.login_channel != LoginChannel.DELIVERY:
        raise AuthorizationDeniedError("Delivery channel access is required")
    return context
