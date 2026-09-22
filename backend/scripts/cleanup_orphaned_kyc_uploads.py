"""Delete expired KYC uploads that were staged but never attached.

Production schedule recommendation: run this daily with `--execute` after monitoring a
dry-run in the target environment.
"""

import argparse
import asyncio

from app.config.app import get_settings
from app.modules.customers.cleanup import OrphanedUploadCleanupService
from app.modules.customers.dependencies import get_storage
from app.shared.database.session import AsyncSessionLocal


async def _run(retention_hours: int, execute: bool) -> int:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        result = await OrphanedUploadCleanupService(session, get_storage(settings)).cleanup(
            retention_hours=retention_hours,
            dry_run=not execute,
        )
        if execute:
            await session.commit()
        print(
            {
                "dryRun": result.dry_run,
                "retentionHours": result.retention_hours,
                "expiredBefore": result.expired_before.isoformat(),
                "count": result.count,
                "fileIds": result.file_ids,
            }
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-hours", type=int, default=get_settings().staged_upload_retention_hours)
    parser.add_argument("--execute", action="store_true", help="Delete rows and storage objects. Omit for dry-run.")
    args = parser.parse_args()
    return asyncio.run(_run(args.retention_hours, args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
