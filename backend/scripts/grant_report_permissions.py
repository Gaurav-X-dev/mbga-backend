"""Grant report permissions to merchant roles for this deployment.

Usage:
    python scripts/grant_report_permissions.py --dry-run
    python scripts/grant_report_permissions.py --execute
    python scripts/grant_report_permissions.py --role accountant --execute
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.app import get_settings
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RolePermission

GRANTS = {
    "manager": ("reports.view", "reports.export", "expenses.view", "payments.reconcile"),
    "accountant": ("reports.view", "reports.export", "expenses.view", "payments.reconcile"),
    "godown_stock_manager": ("reports.view", "reports.export"),
    "salesperson": ("reports.view", "reports.export"),
}


async def grant(role_code: str, execute: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, class_=AsyncSession)() as db:
        role = await db.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            print(f"Role {role_code!r} does not exist. Run scripts/seed_rbac.py first.")
            await engine.dispose()
            return 1
        held = set((await db.execute(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id == role.id))).scalars())
        missing = [code for code in GRANTS[role_code] if code not in held]
        print(f"Role: {role_code}\nTo grant: {missing or '(nothing)'}")
        if not execute or not missing:
            if missing:
                print("Dry run. Re-run with --execute.")
            await engine.dispose()
            return 0
        now = datetime.now(UTC)
        for code in missing:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                print(f"Skipped {code}: run scripts/seed_rbac.py first")
                continue
            db.add(RolePermission(role_id=role.id, permission_id=permission.id, granted_at=now, granted_by=None))
        await db.commit()
        print("Report permissions granted. Sign in again or wait for the permission cache to expire.")
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(GRANTS), default="manager")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    return asyncio.run(grant(args.role, args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
