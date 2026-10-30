"""Create the generated initial draft once; never overwrite operator edits."""

import asyncio
from types import SimpleNamespace

from app.modules.legal_pages.schemas import SaveDraft
from app.modules.legal_pages.service import LegalPageService
from app.shared.database.session import AsyncSessionLocal, engine


async def main():
    async with AsyncSessionLocal() as session:
        service = LegalPageService(session)
        current = await service.editor()
        if current.revision == 0:
            current = await service.save(
                SaveDraft(expected_revision=0, content=current.draft),
                SimpleNamespace(
                    user_id="system-policy-seed", display_name="Generated initial draft"
                ),
            )
            print("Initial private policy draft created; revision", current.revision)
        else:
            print("Existing policy preserved; revision", current.revision)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
