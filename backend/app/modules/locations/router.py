"""The delivery area, for the address forms on every app.

Public, like `/constants` and for the same reason: a customer picks their city before they
have an account, so there is no token to check. Nothing here is private - a state and a city.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.locations.models import City, PostalLocation, State
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/locations", tags=["Locations"])

_CAMEL = ConfigDict(populate_by_name=True, from_attributes=True)


class StateOption(BaseModel):
    """`code` is what stays stable; `name` is what an address stores and a person reads."""

    code: str
    name: str
    model_config = _CAMEL


class CityOption(BaseModel):
    name: str
    state_code: str = Field(alias="stateCode")
    state_name: str = Field(alias="stateName")
    model_config = _CAMEL


class PostOfficeOption(BaseModel):
    office_name: str = Field(alias="officeName")
    office_type: str | None = Field(default=None, alias="officeType")
    delivery_available: bool = Field(alias="deliveryAvailable")
    latitude: float | None = None
    longitude: float | None = None
    model_config = _CAMEL


class PincodeLookupResponse(BaseModel):
    pincode: str
    serviceable: bool
    district: str
    state: str
    offices: list[PostOfficeOption]
    model_config = _CAMEL


@router.get("/states", response_model=list[StateOption], summary="States the agency delivers in")
async def list_states(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[StateOption]:
    rows = await session.scalars(
        select(State).where(State.is_active.is_(True)).order_by(State.sort_order, State.name)
    )
    return [StateOption(code=row.code, name=row.name) for row in rows]


@router.get(
    "/states/{stateCode}/cities",
    response_model=list[CityOption],
    responses=error_responses(404),
    summary="Cities in one state",
)
async def list_cities(
    state_code: Annotated[str, Path(alias="stateCode", max_length=10)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[CityOption]:
    """An unknown state returns an empty list rather than a 404.

    The app asks with whatever is in its state box, which may be a value typed before this
    table existed. An error there would break an address form over a state nobody has added
    yet; an empty list leaves the city box free text, which is what it was anyway.
    """
    state = await session.scalar(
        select(State).where(State.code == state_code.upper(), State.is_active.is_(True))
    )
    if state is None:
        return []
    rows = await session.scalars(
        select(City)
        .where(City.state_id == state.id, City.is_active.is_(True))
        .order_by(City.sort_order, City.name)
    )
    return [CityOption(name=row.name, state_code=state.code, state_name=state.name) for row in rows]


@router.get("/cities", response_model=list[CityOption], summary="Cities, optionally by state")
async def search_cities(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    state: Annotated[
        str | None, Query(description="State code or name. Omit for every city.")
    ] = None,
) -> list[CityOption]:
    """One call for a form that holds a state name rather than its code - which is what an
    address row stores, and therefore what an edit screen has in hand."""
    statement = (
        select(City, State)
        .join(State, State.id == City.state_id)
        .where(City.is_active.is_(True), State.is_active.is_(True))
        .order_by(State.sort_order, City.sort_order, City.name)
    )
    if state:
        wanted = state.strip()
        statement = statement.where((State.code == wanted.upper()) | (State.name == wanted))
    rows = (await session.execute(statement)).all()
    return [
        CityOption(name=city.name, state_code=parent.code, state_name=parent.name)
        for city, parent in rows
    ]


@router.get(
    "/pincodes/{pincode}",
    response_model=PincodeLookupResponse,
    responses=error_responses(404, 422),
    summary="Resolve a pincode into its address options",
)
async def lookup_pincode(
    pincode: Annotated[str, Path(pattern=r"^\d{6}$")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PincodeLookupResponse:
    rows = list(
        await session.scalars(
            select(PostalLocation)
            .where(PostalLocation.pincode == pincode, PostalLocation.is_active.is_(True))
            .order_by(PostalLocation.delivery_available.desc(), PostalLocation.office_name)
        )
    )
    if not rows:
        from fastapi import status

        from app.shared.exceptions.api_error import ApiError

        raise ApiError("PINCODE_NOT_FOUND", status.HTTP_404_NOT_FOUND, "Pincode was not found.")
    return PincodeLookupResponse(
        pincode=pincode,
        serviceable=any(row.delivery_available for row in rows),
        district=rows[0].district_name,
        state=rows[0].state_name,
        offices=[
            PostOfficeOption(
                office_name=row.office_name,
                office_type=row.office_type,
                delivery_available=row.delivery_available,
                latitude=row.latitude,
                longitude=row.longitude,
            )
            for row in rows
        ],
    )
