"""Deliver queued notifications to FCM.

The business modules queue events on their own transaction and never send anything - a
Firebase outage must not be the reason an order fails. This is what actually delivers them.

Run it as a loop in production (systemd, a container, or Task Scheduler every minute):

    python scripts/send_notifications.py --once          # one pass, then exit
    python scripts/send_notifications.py --watch         # keep going, every 30s
    python scripts/send_notifications.py --once --dry-run  # resolve devices, send nothing

`--dry-run` is the one to start with: it reports how many rows are due and how many devices
each would reach, without a Firebase credential and without sending anything. If it reports
`noDevices` for everything, the apps are not sending `device.fcm_token` yet - the backend is
fine and the app is the thing to fix.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.app import get_settings
from app.modules.notifications.dispatcher import NotificationDispatcher
from app.modules.notifications.projects import FcmProjects
from app.shared.database.session import AsyncSessionLocal

POLL_SECONDS = 30


def _load_projects(dry_run: bool) -> FcmProjects | None:
    """The per-app FCM clients, or None when push is off or deliberately skipped.

    Each app is its own Firebase project. What is configured is printed up front, so a
    missing credential is visible before anybody waits for a notification that was never
    going anywhere. An app with no credential is skipped rather than fatal - its rows stay
    queued and go out once it is configured.
    """
    settings = get_settings()
    if dry_run:
        print("Dry run: devices will be resolved, nothing will be sent.")
        return None
    if not settings.fcm_enabled:
        print("FCM_ENABLED is false. Nothing will be sent; rows stay queued.")
        return None
    projects = FcmProjects(settings)
    ready = projects.configured()
    if not ready:
        print("No app has a usable Firebase credential. Rows stay queued.")
        return None
    print("Sending through:")
    for channel, project_id in sorted(ready.items()):
        print(f"  {channel:9} -> {project_id}")
    missing = {"MERCHANT", "CUSTOMER", "DELIVERY"} - set(ready)
    if missing:
        print(f"  not configured: {', '.join(sorted(missing))} - their rows stay queued")
    return projects


async def _run(once: bool, dry_run: bool) -> int:
    settings = get_settings()
    projects = _load_projects(dry_run)
    try:
        while True:
            async with AsyncSessionLocal() as session:
                report = await NotificationDispatcher(session, projects).run(limit=settings.fcm_batch_size)
            if report.considered or once:
                print(report.as_dict())
            if once:
                return 0
            await asyncio.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        if projects is not None:
            await projects.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="One pass, then exit (default).")
    mode.add_argument("--watch", action="store_true", help=f"Keep running, every {POLL_SECONDS}s.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve devices but send nothing.")
    args = parser.parse_args()
    return asyncio.run(_run(once=not args.watch, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
