"""Inserts missing states and cities. Idempotent, and never overwrites an edited name."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.locations.models import City, State
from app.modules.locations.seeds import SEED_STATES, slugify


class LocationSeedRunner:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> dict[str, int]:
        """Add what is missing. A row somebody renamed is left exactly as they left it.

        Matching is by `code` for a state and by `(state, name)` for a city, so re-running
        after an operator has reworded "Gurugram" adds nothing and changes nothing.
        """
        now = datetime.now(UTC)
        states_created = cities_created = 0

        for order, seed in enumerate(SEED_STATES):
            state = await self.session.scalar(select(State).where(State.code == seed.code))
            if state is None:
                state = State(
                    id=str(uuid4()),
                    code=seed.code,
                    name=seed.name,
                    sort_order=order,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(state)
                await self.session.flush()
                states_created += 1

            # Matched on the slug, not the name: an operator who prefers "Gurgaon" keeps it,
            # and re-running must not put "Gurugram" back beside it.
            existing = {
                row.slug
                for row in await self.session.scalars(select(City).where(City.state_id == state.id))
            }
            for city_order, name in enumerate(seed.cities):
                slug = slugify(name)
                if slug in existing:
                    continue
                self.session.add(
                    City(
                        id=str(uuid4()),
                        state_id=state.id,
                        slug=slug,
                        name=name,
                        sort_order=city_order,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
                cities_created += 1

        await self.session.commit()
        return {"states_created": states_created, "cities_created": cities_created}
