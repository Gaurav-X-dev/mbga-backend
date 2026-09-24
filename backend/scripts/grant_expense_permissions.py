"""Grant the expense permissions to a merchant role in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
`expenses.view` and `expenses.manage` are already seeded as permissions, but no role holds
them: the seed deliberately keeps `manager` narrow and the test suite asserts that. Who may
record what the business spends is a per-deployment decision, the same rule
`grant_merchant_kyc_permissions.py` and `grant_pricing_permissions.py` follow.

    python scripts/grant_expense_permissions.py --dry-run
    python scripts/grant_expense_permissions.py --execute
    python scripts/grant_expense_permissions.py --role accountant --execute
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
    # Runs the Expenses screen: records spend and manages the category list.
    "manager": ("expenses.view", "expenses.manage"),
    "accountant": ("expenses.view", "expenses.manage"),
    # Files day-to-day spend (fuel, tolls) but does not reshape the category list. Kept
    # equal to manage for now because the Add sheet is the only write screen that exists;
    # split it here the day a category-management screen ships.
    "godown_stock_manager": ("expenses.view", "expenses.manage"),
    # Sees the spend report, records nothing.
    "salesperson": ("expenses.view",),
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
