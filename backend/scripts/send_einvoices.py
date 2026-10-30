"""File queued invoices with the GST portal and write back their IRNs.

A delivery confirmation queues a row and never calls anybody - the portal must not be able to
stop a handover from recording. This is what actually files them.

Run it as a loop in production (systemd, a container, or Task Scheduler every minute):

    python scripts/send_einvoices.py --once            # one pass, then exit
    python scripts/send_einvoices.py --watch           # keep going, every 60s
    python scripts/send_einvoices.py --once --dry-run  # build payloads, send nothing

`--dry-run` is the one to start with. It builds every payload and reports what would be
filed, without a provider credential and without sending anything, so missing GSTINs,
addresses and vehicle numbers surface before a single document reaches the portal. Data the
portal would reject is reported here with the field named.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.app import get_settings
from app.modules.einvoice.service import EInvoiceDispatcher
from app.shared.database.session import AsyncSessionLocal

POLL_SECONDS = 60


def _announce(dry_run: bool) -> bool:
    """Say what this process is set up to do, and whether it can do anything at all."""
    settings = get_settings()
    if dry_run:
        print("Dry run: payloads will be built, nothing will be sent.")
        return True
    if not settings.einvoice_enabled:
        print("EINVOICE_ENABLED is false. Nothing will be filed; rows stay queued.")
        return False
    missing = [
        name
        for name, value in (
            ("EINVOICE_EMAIL", settings.einvoice_email),
            ("EINVOICE_USERNAME", settings.einvoice_username),
            ("EINVOICE_PASSWORD", settings.einvoice_password),
            ("EINVOICE_CLIENT_ID", settings.einvoice_client_id),
            ("EINVOICE_CLIENT_SECRET", settings.einvoice_client_secret),
            ("EINVOICE_BEARER_TOKEN", settings.einvoice_bearer_token),
            ("EINVOICE_GSTIN", settings.einvoice_gstin),
            ("EINVOICE_IP_ADDRESS", settings.einvoice_ip_address),
        )
        if not value
    ]
    if missing:
        print(f"Not configured: {', '.join(missing)}. Rows stay queued.")
        return False
    print(f"Filing through {settings.einvoice_base_url} as GSTIN {settings.einvoice_gstin}.")
    if "staging" in settings.einvoice_base_url:
        # Worth saying out loud: a staging IRN looks exactly like a real one and is not
        # legally valid. Somebody reading this log should know which they are looking at.
        print("  This is the provider's STAGING host - the IRNs it returns are not valid.")
    return True


async def _pass(dry_run: bool) -> dict[str, int]:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        dispatcher = EInvoiceDispatcher(session, settings, dry_run=dry_run)
        try:
            report = await dispatcher.run_once()
        finally:
            await dispatcher.aclose()
    return report.as_dict()


async def _watch(dry_run: bool) -> None:
    while True:
        report = await _pass(dry_run)
        if report["considered"]:
            print(report, flush=True)
        await asyncio.sleep(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="One pass, then exit.")
    group.add_argument("--watch", action="store_true", help=f"Keep going, every {POLL_SECONDS}s.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads and report, but send nothing and change nothing.",
    )
    args = parser.parse_args()

    usable = _announce(args.dry_run)
    if args.once:
        print(asyncio.run(_pass(args.dry_run)))
        return 0
    if not usable:
        # Looping every minute to print the same complaint helps nobody. Exiting non-zero
        # lets systemd's restart back-off do the waiting, and the reason stays in the log.
        return 1
    asyncio.run(_watch(args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
