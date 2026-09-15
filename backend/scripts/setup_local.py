from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> int:
    print(f"Running: {' '.join(command)}")
    return subprocess.run(command, cwd=ROOT).returncode


def confirm(prompt: str) -> bool:
    return input(f"{prompt} Type YES to continue: ").strip() == "YES"


def main() -> int:
    print("MBGA local setup helper")
    if not (ROOT / ".env").exists():
        print("BLOCKED: .env is missing. Copy .env.example to .env and add local MySQL credentials.")
        return 1
    if run([sys.executable, "scripts/check_setup.py", "--database"]) != 0:
        print("BLOCKED: setup checker reported a required database problem.")
        return 1
    if confirm("Run Alembic migrations on the configured local database?"):
        if run(["alembic", "upgrade", "head"]) != 0:
            return 1
    else:
        print("SKIPPED: migrations")
        return 0
    if confirm("Run RBAC seed runner twice to verify idempotency?"):
        if run([sys.executable, "scripts/seed_rbac.py"]) != 0:
            return 1
        if run([sys.executable, "scripts/seed_rbac.py"]) != 0:
            return 1
    if run([sys.executable, "-m", "compileall", "app", "tests", "scripts"]) != 0:
        return 1
    if run([sys.executable, "-m", "pytest", "-m", "unit", "-v"]) != 0:
        return 1
    print("Local setup completed for the confirmed steps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
