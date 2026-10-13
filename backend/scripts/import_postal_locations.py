"""Usage: python scripts/import_postal_locations.py path/to/postal.csv"""

import argparse
import asyncio
import io

from app.modules.locations.importer import import_postal_csv
from app.shared.database.session import AsyncSessionLocal


async def main(path: str) -> None:
    async with AsyncSessionLocal() as session:
        # This is a one-shot CLI job; streaming keeps the 150k+ row file out of memory.
        with open(path, "rb") as raw:  # noqa: ASYNC230
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            print(await import_postal_csv(session, text))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    asyncio.run(main(parser.parse_args().csv_path))
