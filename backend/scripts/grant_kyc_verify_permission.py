"""Let the people who already review KYC read the number they are reviewing.

`customers.verify` guards the one route that returns a document identifier in full - the
reviewer's "show me the Aadhaar so I can check it against the scan". It is seeded, and on a
live deployment only `super_admin` holds it, so the agency's own reviewers see `XXXXXXXX9012`
and are asked to decide whether it matches a photograph.

**Granted to whoever already holds `customers.review`**, and to nobody else. That is the
precise set of people being asked the question, so this gives no one a right they did not
already have a reason for - and it needs no list of role names here that would drift from the
deployment's own.

    python scripts/grant_kyc_verify_permission.py            # dry run
    python scripts/grant_kyc_verify_permission.py --execute
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config.app import get_settings
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RolePermission
from app.shared.database.session import AsyncSessionLocal

REVIEW = "customers.review"
VERIFY = "customers.verify"


async def grant(execute: bool) -> int:
    async with AsyncSessionLocal() as db:
        verify = await db.scalar(select(Permission).where(Permission.code == VERIFY))
        if verify is None:
            print(f"{VERIFY!r} is not seeded. Run the RBAC seeder first.")
            return 1

        reviewers = set(
            (
                await db.execute(
                    select(RolePermission.role_id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .where(Permission.code == REVIEW)
                )
            ).scalars()
        )
        already = set(
            (
                await db.execute(
                    select(RolePermission.role_id).where(
                        RolePermission.permission_id == verify.id
                    )
                )
            ).scalars()
        )
        missing = sorted(reviewers - already)

        names = {
            role.id: role.code
            for role in await db.scalars(
                select(Role).where(Role.id.in_(reviewers | already))
            )
        }
        print(f"Roles that review KYC : {sorted(names[r] for r in reviewers) or '(none)'}")
        print(f"Already able to verify: {sorted(names[r] for r in already) or '(none)'}")
        print(f"To grant              : {sorted(names[r] for r in missing) or '(nothing)'}")

        if not missing:
            print("\nNothing to do.")
            return 0
        if not execute:
            print("\nDry run. Re-run with --execute to apply.")
            return 0

        now = datetime.now(UTC)
        for role_id in missing:
            db.add(
                RolePermission(
                    role_id=role_id,
                    permission_id=verify.id,
                    granted_at=now,
                    granted_by=None,
                )
            )
        await db.commit()
        settings = get_settings()
        print(f"\nGranted {VERIFY} to {len(missing)} role(s).")
        print("Staff already signed in keep their old permissions until the cache expires")
        print(f"(PERMISSION_CACHE_TTL_SECONDS={settings.permission_cache_ttl_seconds}) or they sign in again.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Apply the grant.")
    args = parser.parse_args()
    return asyncio.run(grant(execute=args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
