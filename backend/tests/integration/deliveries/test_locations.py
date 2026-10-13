"""States and cities, read from the table rather than a list in the source.

The states were a tuple of six names in the seeder and the city box was free text, so
"Gurgaon", "Gurugram" and "gurugram " were three places in the reports. A delivery area is
business data: it changes when the agency opens a route, not when the backend ships.
"""

import pytest
from sqlalchemy import select, update

from app.modules.locations.models import City, State
from app.modules.locations.seed_runner import LocationSeedRunner
from tests.integration.authentication.conftest import (  # noqa: F401 - fixtures
    AuthEnv,
    _prepared_database,
    database_url,
    env,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

CUSTOMER = "/api/v1/customer/locations"
MERCHANT = "/api/v1/merchant/locations"
DELIVERY = "/api/v1/delivery/locations"


async def seed(env) -> dict:
    async with env.sessions() as db:
        return await LocationSeedRunner(db).run()


# --- The catalogue --------------------------------------------------------------------------


async def test_the_seeded_state_is_served(env):
    await seed(env)

    response = await env.client.get(f"{CUSTOMER}/states")

    assert response.status_code == 200, response.text
    assert {row["code"]: row["name"] for row in response.json()} == {"HR": "Haryana"}


async def test_its_cities_come_with_it(env):
    await seed(env)

    cities = (await env.client.get(f"{CUSTOMER}/states/HR/cities")).json()

    names = [row["name"] for row in cities]
    assert "Gurugram" in names
    assert "Faridabad" in names
    assert len(names) == 22
    assert all(row["stateName"] == "Haryana" for row in cities)


async def test_the_cities_are_in_the_order_the_dropdown_wants(env):
    await seed(env)

    names = [row["name"] for row in (await env.client.get(f"{CUSTOMER}/states/HR/cities")).json()]

    assert names == sorted(names)


async def test_the_state_code_is_not_case_sensitive(env):
    """An app that stores "hr" should not get an empty city list for it."""
    await seed(env)

    assert (await env.client.get(f"{CUSTOMER}/states/hr/cities")).json()


async def test_an_unknown_state_is_empty_not_an_error(env):
    """The app asks with whatever is in its state box, which may predate this table. An error
    there would break the address form over a state nobody has added yet."""
    await seed(env)

    response = await env.client.get(f"{CUSTOMER}/states/XX/cities")

    assert response.status_code == 200
    assert response.json() == []


async def test_cities_can_be_asked_for_by_state_name(env):
    """An address row stores the name, not the code, so an edit screen has the name in hand."""
    await seed(env)

    by_name = (await env.client.get(f"{CUSTOMER}/cities?state=Haryana")).json()
    by_code = (await env.client.get(f"{CUSTOMER}/cities?state=HR")).json()

    assert by_name == by_code
    assert len(by_name) == 22


async def test_every_app_reads_the_same_list(env):
    await seed(env)

    for prefix in (CUSTOMER, MERCHANT, DELIVERY):
        response = await env.client.get(f"{prefix}/states")
        assert response.status_code == 200, prefix
        assert [row["code"] for row in response.json()] == ["HR"], prefix


async def test_the_list_is_public(env):
    """A customer picks their city before they have an account."""
    await seed(env)

    assert (await env.client.get(f"{CUSTOMER}/states")).status_code == 200


# --- Editing it -----------------------------------------------------------------------------


async def test_a_retired_city_stops_being_offered(env):
    """A route the agency drops. The rows stay, because old addresses still name them."""
    await seed(env)
    await env.execute(update(City).where(City.name == "Nuh").values(is_active=False))

    names = [row["name"] for row in (await env.client.get(f"{CUSTOMER}/states/HR/cities")).json()]

    assert "Nuh" not in names
    assert await env.scalar(select(City).where(City.name == "Nuh")) is not None


async def test_the_seeder_adds_nothing_the_second_time(env):
    await seed(env)

    assert await seed(env) == {"states_created": 0, "cities_created": 0}


async def test_a_reworded_city_is_left_alone(env):
    """An operator who prefers "Gurgaon" keeps it; re-running must not put the other name back."""
    await seed(env)
    await env.execute(update(City).where(City.name == "Gurugram").values(name="Gurgaon"))

    await seed(env)

    names = [row["name"] for row in (await env.client.get(f"{CUSTOMER}/states/HR/cities")).json()]
    assert "Gurgaon" in names
    assert "Gurugram" not in names


async def test_a_state_added_by_hand_is_served(env):
    """What the panel will do. More states need no release."""
    from datetime import UTC, datetime
    from uuid import uuid4

    await seed(env)
    now = datetime.now(UTC)
    async with env.sessions() as db:
        state = State(
            id=str(uuid4()), code="MP", name="Madhya Pradesh",
            sort_order=1, is_active=True, created_at=now, updated_at=now,
        )
        db.add(state)
        await db.flush()
        db.add(City(
            id=str(uuid4()), state_id=state.id, slug="indore", name="Indore",
            sort_order=0, is_active=True, created_at=now, updated_at=now,
        ))
        await db.commit()

    states = {row["code"] for row in (await env.client.get(f"{CUSTOMER}/states")).json()}
    cities = [row["name"] for row in (await env.client.get(f"{CUSTOMER}/states/MP/cities")).json()]

    assert states == {"HR", "MP"}
    assert cities == ["Indore"]
