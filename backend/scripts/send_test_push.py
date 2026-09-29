"""Send a test push to one person's phone, for checking an app is wired up.

Finds their newest live device token, works out which Firebase project it belongs to from the
channel they signed in on, and sends one notification straight through FCM.

This is a **diagnostic**, not part of the platform. It writes nothing to the outbox and creates no
business record - it answers one question: does a notification sent from this machine reach that
handset? When it says `ok` and nothing appears on the phone, the remaining causes are all on the
device: notification permission, a Do Not Disturb mode, a missing notification channel, or the app
sitting in the foreground where Android hands the message to the app instead of the tray.

    python scripts/send_test_push.py 8423331963
    python scripts/send_test_push.py 8423331963 --title "New delivery assigned" --body "Order ORD-2609-0012 is yours."
    python scripts/send_test_push.py 8423331963 --all-devices
    python scripts/send_test_push.py --list
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.app import get_settings
from app.modules.notifications.fcm import PushMessage
from app.modules.notifications.projects import FcmProjects

#: A real FCM registration token is ~140 characters. Anything much shorter is a placeholder an app
#: sent while its Firebase setup was still incomplete, and sending to it only produces a confusing
#: error - so they are reported rather than used.
REAL_TOKEN_LENGTH = 40

DEVICES = text(
    "SELECT s.push_token AS token, s.login_channel AS channel, s.device_type AS device, "
    "       s.created_at AS signed_in, u.mobile_number AS mobile, u.full_name AS name "
    "FROM login_sessions s "
    "JOIN users u ON u.id = s.user_id "
    "WHERE u.mobile_number LIKE :mobile "
    "  AND s.push_token IS NOT NULL "
    "  AND s.revoked_at IS NULL "
    "ORDER BY s.created_at DESC"
)

EVERY_DEVICE = text(
    "SELECT u.mobile_number AS mobile, COALESCE(u.full_name, '-') AS name, "
    "       s.login_channel AS channel, CHAR_LENGTH(s.push_token) AS length, "
    "       s.created_at AS signed_in "
    "FROM login_sessions s "
    "JOIN users u ON u.id = s.user_id "
    "WHERE s.push_token IS NOT NULL AND s.revoked_at IS NULL "
    "ORDER BY s.created_at DESC"
)


async def _sessions():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return engine, async_sessionmaker(engine, class_=AsyncSession)


async def list_devices() -> int:
    """Every live token in the database, so you can see what there is to send to."""
    engine, sessions = await _sessions()
    async with sessions() as db:
        rows = list(await db.execute(EVERY_DEVICE))
    await engine.dispose()

    if not rows:
        print("No device has registered a push token yet.")
        return 1
    print(f"{'signed in':20} {'channel':10} {'mobile':16} {'name':18} token")
    for row in rows:
        kind = "real" if row.length > REAL_TOKEN_LENGTH else f"PLACEHOLDER ({row.length} chars)"
        print(f"{str(row.signed_in)[:19]:20} {row.channel or '-':10} {row.mobile:16} {row.name[:18]:18} {kind}")
    return 0


async def send(mobile: str, title: str, body: str, *, all_devices: bool) -> int:
    engine, sessions = await _sessions()
    async with sessions() as db:
        rows = list(await db.execute(DEVICES, {"mobile": f"%{mobile}%"}))
    await engine.dispose()

    if not rows:
        print(f"No live device token for {mobile}.")
        print("The app has signed in but never sent an fcm_token, or the session was revoked.")
        print("Run with --list to see every device that does have one.")
        return 1

    usable = [row for row in rows if len(row.token) > REAL_TOKEN_LENGTH]
    if not usable:
        print(f"{mobile} has {len(rows)} session(s), but every token is a placeholder:")
        for row in rows:
            print(f"  {row.channel}: {row.token!r}")
        print("\nThe app is sending a stand-in rather than a real Firebase token.")
        return 1

    targets = usable if all_devices else usable[:1]
    projects = FcmProjects(get_settings())
    failures = 0
    for row in targets:
        print(f"\n{row.name or mobile} · {row.channel} · signed in {str(row.signed_in)[:19]}")
        client = projects.client_for(row.channel)
        if client is None:
            print(f"  no Firebase project configured for the {row.channel} app - nothing sent")
            failures += 1
            continue
        print(f"  project : {client.credentials.project_id}")
        print(f"  token   : …{row.token[-12:]}")
        result = await client.send(
            row.token,
            PushMessage(title=title, body=body, data={"type": "TEST"}),
        )
        if result.ok:
            print("  sent    : ok")
        else:
            failures += 1
            print(f"  sent    : FAILED - {result.error}")
            if result.token_dead:
                print("            this token is dead; the app must register a new one")
            if result.misrouted:
                print("            the token belongs to a different Firebase project")
    await projects.aclose()

    if not failures:
        print("\nFCM accepted it. If nothing appears on the phone, the message reached Google and")
        print("stopped on the device - check notification permission, Do Not Disturb, and whether")
        print("the app was in the foreground (Android gives it to the app, not the tray).")
    return 1 if failures else 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mobile", nargs="?", help="Mobile number, with or without the country code.")
    parser.add_argument("--title", default="Test notification", help="Notification title.")
    parser.add_argument(
        "--body",
        default="If you can read this, push notifications are working.",
        help="Notification body.",
    )
    parser.add_argument(
        "--all-devices",
        action="store_true",
        help="Send to every live device, not just the most recent one.",
    )
    parser.add_argument("--list", action="store_true", help="List every device with a token.")
    args = parser.parse_args()

    if args.list:
        return await list_devices()
    if not args.mobile:
        parser.error("give a mobile number, or --list")
    if not get_settings().fcm_enabled:
        print("FCM_ENABLED is false in this environment - nothing would be sent.")
        return 1
    return await send(args.mobile, args.title, args.body, all_devices=args.all_devices)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
