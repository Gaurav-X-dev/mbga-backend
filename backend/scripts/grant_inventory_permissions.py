"""Grant the warehouse permissions to a merchant role in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
`inventory.view` and `inventory.adjust` are already seeded as permissions, but the seed
deliberately keeps `manager` narrow and the test suite asserts that. Who may see and change
stock is a per-deployment decision, the same rule `grant_pricing_permissions.py`,
`grant_expense_permissions.py` and `grant_order_permissions.py` follow.

The grants below are spec §2.1's role matrix, which for the warehouse is short:

    permission          MANAGER  SALESPERSON  GODOWN_INCHARGE  ACCOUNTANT
    inventory.view         x                         x
    inventory.adjust       x                         x

A salesperson and an accountant get neither, and that is the spec's call rather than an
oversight: a salesperson quoting an order does not need the godown's counts, and an accountant
reconciles money rather than cylinders. Giving `inventory.adjust` away widely is how a count
gets corrected by somebody who did not walk the floor and recount it.

    python scripts/grant_inventory_permissions.py --dry-run
    python scripts/grant_inventory_permissions.py --execute
    python scripts/grant_inventory_permissions.py --role godown_stock_manager --execute
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
    # Runs the business, so reads and adjusts.
    "manager": ("inventory.view", "inventory.adjust"),
    # Runs the godown: this is their screen. Counts the cylinders and records the movements.
    "godown_stock_manager": ("inventory.view", "inventory.adjust"),
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
            print(f"  role '{role_code}' has no inventory grants defined - skipped")
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
