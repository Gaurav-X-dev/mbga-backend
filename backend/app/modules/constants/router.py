"""Reference data the apps fill their dropdowns from.

One public endpoint over the `constants` table. Operators can reword a label in the database
and both apps pick it up with no release.

Public on purpose: a customer chooses their merchant *before* they have an account, so there
is no token to check. Nothing here is private - only a key and the label shown beside it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.audit import ClientInfo
from app.modules.authentication.dependencies import get_client_info
from app.modules.authentication.throttle import RequestThrottle
from app.modules.constants.models import Constant
from app.modules.merchants.models import Merchant
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(tags=["Constants"])

# Merchants are not rows in `constants`: they are live business data with their own table,
# their own lifecycle and their own status rules. Copying them in would mean every new
# merchant had to be written twice and could disappear from the app if the second write was
# missed. They are read from `merchants` and presented in the same key/value shape.
MERCHANTS_GROUP = "merchants"


class ConstantOption(BaseModel):
    """One row as the apps see it.

    `constKey` is what the app sends back to the API; `constValue` is what it shows the user.
    """

    id: str
    const_key: str = Field(alias="constKey")
    const_value: str = Field(alias="constValue")
    const_group: str = Field(alias="constGroup")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


@router.get(
    "/constants",
    response_model=list[ConstantOption],
    responses=error_responses(429),
    summary="Key/value constants for both apps",
)
async def constants(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[ClientInfo, Depends(get_client_info)],
    group: Annotated[
        str | None,
        Query(description="Return one group only, e.g. merchants, customerTypes, documentTypes, pricingTiers, states."),
    ] = None,
) -> list[ConstantOption]:
    """Every constant, or one group of them.

    An unknown group returns an empty list rather than an error: the app asks for a group it
    knows, and a typo that silently yields nothing is easier to see in the response than a
    validation error buried in a dropdown that never opened.
    """
    # Unauthenticated, so it is limited per client IP like the other public endpoints.
    try:
        await RequestThrottle(session, settings.jwt_signing_secret).hit(
            "constants:ip", client.ip_address, settings.constants_limit_per_ip
        )
    finally:
        await session.commit()

    wanted = (group or "").strip()
    options: list[ConstantOption] = []

    if not wanted or wanted == MERCHANTS_GROUP:
        # Only merchants a customer could actually register under. A blocked or unapproved
        # merchant is absent rather than shown-and-rejected. The display code is the key;
        # Merchant.id never leaves the backend.
        merchants = await session.scalars(
            select(Merchant)
            .where(Merchant.status == "ACTIVE", Merchant.approval_status == "APPROVED")
            .order_by(Merchant.name)
        )
        # `id` carries the code as well: a merchant has no row in `constants`, and the
        # internal UUID has no business reaching a public caller.
        options += [
            ConstantOption(id=m.code, const_key=m.code, const_value=m.name, const_group=MERCHANTS_GROUP)
            for m in merchants
        ]

    if wanted != MERCHANTS_GROUP:
        statement = select(Constant).order_by(Constant.const_group, Constant.sort_order, Constant.const_key)
        if wanted:
            statement = statement.where(Constant.const_group == wanted)
        options += [
            ConstantOption(
                id=row.id,
                const_key=row.const_key,
                const_value=row.const_value,
                const_group=row.const_group,
            )
            for row in await session.scalars(statement)
        ]
    return options
