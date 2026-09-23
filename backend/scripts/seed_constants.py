"""Insert the constant rows the apps read. Safe to re-run; edited labels are kept."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.app import get_settings
from app.modules.constants.seeds import ConstantsSeedRunner


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, class_=AsyncSession)() as session:
        print(await ConstantsSeedRunner(session).run())
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
