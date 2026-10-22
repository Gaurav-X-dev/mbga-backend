"""Grant `payments.reconcile` to a merchant role in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
`payments.reconcile` is seeded as a permission but only `super_admin` holds it, so on a live
deployment nobody inside the agency can settle a pending UPI collection against the bank - the
Payments screen lists them and offers no way out of `PENDING`. Who signs off that the money
arrived is a per-deployment decision, the same rule `grant_expense_permissions.py` and
`grant_pricing_permissions.py` follow.

**`collect` and `reconcile` are deliberately not given to the same people.** Whoever takes the
money should not also be the one confirming it reached the bank, or the check is no check at
all. `salesperson` keeps `payments.collect` and is absent here on purpose.

    python scripts/grant_payment_permissions.py --dry-run
    python scripts/grant_payment_permissions.py --execute
    python scripts/grant_payment_permissions.py --role accountant --execute
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.app import get_settings
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RolePermission

GRANTS: dict[str, tuple[str, ...]] = {
    # Runs the agency. Already holds view and collect; this is what lets the Payments screen's
    # Pending list actually be worked rather than only read.
    "manager": ("payments.view", "payments.reconcile"),
    # Whose job this is by title. Already holds view and collect.
    "accountant": ("payments.view", "payments.reconcile"),
}


async def grant(role_code: str, execute: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    added = 0
    async with async_sessionmaker(engine, class_=AsyncSession)() as db:
        role = await db.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            print(f"Role {role_code!r} does not exist. Run scripts/seed_rbac.py first.")
            await engine.dispose()
            return 1

        wanted = GRANTS[role_code]
        held = set(
            (
                await db.execute(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                )
            ).scalars()
        )
        missing = [code for code in wanted if code not in held]
        print(f"Role       : {role_code}")
        print(f"Already has: {sorted(set(wanted) & held) or '(none)'}")
        print(f"To grant   : {missing or '(nothing - already complete)'}")

        if not missing:
            await engine.dispose()
            return 0
        if not execute:
            print("\nDry run. Re-run with --execute to apply.")
            await engine.dispose()
            return 0

        now = datetime.now(UTC)
        for code in missing:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                print(f"  skipped {code}: permission not seeded")
                continue
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id,
                    granted_at=now,
                    granted_by=None,
                )
            )
            added += 1
        await db.commit()
        print(f"\nGranted {added} permission(s).")
        print("Staff already signed in keep their old permissions until the cache expires")
        print(f"(PERMISSION_CACHE_TTL_SECONDS={settings.permission_cache_ttl_seconds}) or they sign in again.")
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(GRANTS), default="manager")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Show what would change (default).")
    action.add_argument("--execute", action="store_true", help="Apply the grants.")
    args = parser.parse_args()
    return asyncio.run(grant(args.role, execute=args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
