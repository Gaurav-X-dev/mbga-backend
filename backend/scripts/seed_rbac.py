import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.roles.seed_runner import RBACSeedRunner
from app.shared.database.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await RBACSeedRunner(session).run()
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
