"""Seed the delivery area. Safe to re-run: it adds what is missing and edits nothing."""

import asyncio

from app.modules.locations.seed_runner import LocationSeedRunner
from app.shared.database.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        print(await LocationSeedRunner(session).run())


if __name__ == "__main__":
    asyncio.run(main())
