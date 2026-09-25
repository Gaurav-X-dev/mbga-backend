"""Grant the task permission to merchant roles in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
`tasks.view` is seeded as a permission, but the seed deliberately keeps `manager` narrow and the
test suite asserts that. Who may use a module is a per-deployment decision, the same rule
`grant_pricing_permissions.py`, `grant_expense_permissions.py`, `grant_order_permissions.py`,
`grant_inventory_permissions.py` and `grant_delivery_permissions.py` follow.

Unlike every other module, this one is a **single flat permission held by all four roles**:

    permission     MANAGER  SALESPERSON  GODOWN_INCHARGE  ACCOUNTANT
    tasks.view        x          x              x              x

That is the spec being deliberate, not loose. Anyone holding it can create a task, assign it to
anyone, update anyone's task and post on it - the screens are built that way and do not expect a
403 on somebody else's task, so a `tasks.manage` split would break them quietly rather than
protect anything. If finer control is wanted later it is a product decision to raise, not
something to add here.

    python scripts/grant_task_permissions.py --dry-run
    python scripts/grant_task_permissions.py --execute
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
    "manager": ("tasks.view",),
    "salesperson": ("tasks.view",),
    "godown_stock_manager": ("tasks.view",),
    "accountant": ("tasks.view",),
}


async def grant(role_code: str, execute: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    added = 0
    async with async_sessionmaker(engine, class_=AsyncSession)() as db:
        role = await db.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            print(f"  role '{role_code}' does not exist in this deployment - skipped")
            return 0

        wanted = GRANTS.get(role_code)
        if not wanted:
            print(f"  role '{role_code}' has no task grants defined - skipped")
            return 0

        for code in wanted:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                print(f"  permission '{code}' is not seeded - skipped")
                continue
            existing = await db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if existing is not None:
                print(f"  {role_code} already has {code}")
                continue
            print(f"  {'granting' if execute else 'would grant'} {code} to {role_code}")
            added += 1
            if execute:
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                        granted_at=datetime.now(UTC),
                        granted_by=None,
                    )
                )
        if execute:
            await db.commit()
    await engine.dispose()
    return added


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", action="append", help="Role code. Repeatable. Default: every role below.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print what would change.")
    mode.add_argument("--execute", action="store_true", help="Apply the grants.")
    args = parser.parse_args()

    roles = args.role or list(GRANTS)
    total = 0
    for role_code in roles:
        print(f"{role_code}:")
        total += await grant(role_code, args.execute)

    verb = "Granted" if args.execute else "Would grant"
    print(f"\n{verb} {total} permission(s).")
    if not args.execute and total:
        print("Re-run with --execute to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
