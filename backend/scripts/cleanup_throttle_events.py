"""Delete rate-limit counter rows that have fallen out of their window.

`auth_throttle_events` gets one row per throttled request - every OTP request, every OTP
verify, every check-mobile and every public constants call. Nothing deletes them, so the
table only grows, and each throttle check has to count over a table that keeps getting
longer.

Safe by construction, not by inspection
---------------------------------------
`RequestThrottle.hit()` counts only rows inside `WINDOW` (``created_at >= now - WINDOW``),
so a row older than that can never affect a limit or a `Retry-After`. This script deletes
exactly those rows, and it imports the same `WINDOW` constant the limiter uses rather than
hard-coding an hour - if the window is ever widened, the cleanup widens with it and the two
cannot drift apart.

It does **not** touch `otp_challenges`. The per-mobile OTP limit counts that table, not this
one, and OTP history has its own retention.

Production schedule: run daily with `--execute` after checking a dry-run. On Windows, Task
Scheduler; on Linux, cron:

    python scripts/cleanup_throttle_events.py            # dry-run, prints what would go
    python scripts/cleanup_throttle_events.py --execute
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.config.app import get_settings
from app.modules.authentication.models import AuthThrottleEvent
from app.modules.authentication.session_service import utc_now_naive
from app.modules.authentication.throttle import WINDOW, RequestThrottle
from app.shared.database.session import AsyncSessionLocal


async def _run(execute: bool) -> int:
    settings = get_settings()
    cutoff = utc_now_naive() - WINDOW
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(AuthThrottleEvent)) or 0
        expired = (
            await session.scalar(
                select(func.count()).select_from(AuthThrottleEvent).where(AuthThrottleEvent.created_at < cutoff)
            )
            or 0
        )
        print(f"Window     : {int(WINDOW.total_seconds() // 60)} minutes")
        print(f"Cutoff     : {cutoff.isoformat()} (rows older than this count towards nothing)")
        print(f"Rows total : {total}")
        print(f"Expired    : {expired}")
        print(f"Keeping    : {total - expired} row(s) still inside the window")

        if not expired:
            print("\nNothing to delete.")
            return 0
        if not execute:
            print("\nDry run. Re-run with --execute to delete.")
            return 0

        # Deleted through the limiter's own method, so the definition of "expired" lives in
        # exactly one place.
        removed = await RequestThrottle(session, settings.jwt_signing_secret).purge_expired()
        await session.commit()
        print(f"\nDeleted {removed} expired row(s). Live limits are unchanged.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Delete the rows. Omit for a dry-run.")
    args = parser.parse_args()
    return asyncio.run(_run(args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
