"""One-off transport check for HanuOTP. Sends exactly one real SMS, then exits.

The vendor bills per message and the response contract is not documented, so this script
exists to make that single request observable and safe:

* it refuses to run unless the environment explicitly enables it,
* it refuses to run outside local/development,
* it asks the operator to type SEND before anything leaves the machine,
* it makes one request with zero retries and exits,
* it prints a masked number, the HTTP status and a sanitised body — never the key, the code,
  the full number or the request URL.

Run it against the authentication endpoints only *after* this passes; a sign-in request would
go through throttles and could produce more than one message.

    python scripts/smoke_test_hanuotp.py
"""

import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.app import Settings, get_settings
from app.shared.otp.hanuotp_provider import (
    USER_AGENT,
    _sanitize,
    interpret,
    to_national,
)
from app.shared.otp.provider import OTPDeliveryError, mask_for_log

CONFIRM_WORD = "SEND"


def refuse(message: str) -> None:
    print(f"REFUSED: {message}")
    raise SystemExit(1)


def preflight(settings: Settings) -> str:
    """Every guard that must pass before a single rupee is spent."""
    if not settings.is_local_environment:
        refuse(f"APP_ENV={settings.app_env!r}. This script runs only in local/development/test.")
    if not settings.hanuotp_live_smoke_test_enabled:
        refuse("HANUOTP_LIVE_SMOKE_TEST_ENABLED is not true. Set it in .env to authorise one live SMS.")
    if not settings.hanuotp_api_key:
        refuse("HANUOTP_API_KEY is not set in .env.")
    if not settings.hanuotp_base_url:
        refuse("HANUOTP_BASE_URL is not set in .env.")
    if not settings.hanuotp_smoke_test_mobile:
        refuse("HANUOTP_SMOKE_TEST_MOBILE is not set in .env.")
    raw = settings.hanuotp_smoke_test_mobile.strip()
    try:
        return to_national(raw if raw.startswith("+91") else f"+91{raw.removeprefix('91')}")
    except OTPDeliveryError:
        refuse("HANUOTP_SMOKE_TEST_MOBILE is not a valid Indian mobile number.")
        raise  # unreachable; keeps the type checker honest


async def main() -> int:
    settings = get_settings()
    national = preflight(settings)
    masked = mask_for_log(national)

    # Generated here rather than taken from the database: this checks the transport, and a
    # real challenge would tie a live SMS to a real account's throttle counters.
    otp = f"{secrets.randbelow(10**settings.otp_length):0{settings.otp_length}d}"

    print("HanuOTP live transport check")
    print(f"  destination : {masked}")
    print(f"  template    : {settings.hanuotp_template_id}")
    print(f"  retries     : {settings.hanuotp_max_retries}")
    print("  requests    : exactly 1")
    print()
    print(f"This sends one real SMS and costs one message. Type {CONFIRM_WORD} to continue.")
    try:
        answer = input("> ").strip()
    except EOFError:
        refuse("No confirmation received (stdin is not interactive).")
        return 1
    if answer != CONFIRM_WORD:
        print("Cancelled. Nothing was sent.")
        return 1

    captured: dict[str, object] = {}

    # The provider raises on a body it cannot read as a verdict, which is exactly the case
    # this script exists to observe — so the raw status and sanitised body are captured
    # around it and reported either way.
    import httpx

    async with httpx.AsyncClient(timeout=settings.hanuotp_timeout_seconds) as client:
        try:
            response = await client.get(
                str(settings.hanuotp_base_url),
                # The same headers the provider sends, so this tests the real request rather
                # than a slightly different one.
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                params={
                    "number": national,
                    "OTP": otp,
                    "apikey": settings.hanuotp_api_key,
                    "templatesid": settings.hanuotp_template_id,
                },
            )
        except httpx.HTTPError as exc:
            print()
            print(f"  http status : (no response) {type(exc).__name__}")
            print("  verdict     : FAILED — the request did not reach the vendor.")
            return 1
        captured["status"] = response.status_code
        captured["body"] = _sanitize(
            response, national=national, otp=otp, api_key=settings.hanuotp_api_key
        )

    print()
    print(f"  http status : {captured['status']}")
    print(f"  body        : {captured['body'] or '(empty)'}")

    # Re-run the provider's own interpretation over the captured response so the verdict
    # printed here is the same one the authentication flow would reach.
    try:
        provider_result = interpret(int(captured["status"]), str(captured["body"] or ""))
    except OTPDeliveryError as exc:
        print(f"  verdict     : FAILED — {exc.reason}")
        print()
        print("If the SMS did arrive despite this, the body above shows how the vendor reports")
        print("success. Send it to the backend team so the parser can be adjusted.")
        return 1
    print(f"  verdict     : DELIVERED — reference {provider_result or '(none)'}")
    print()
    print("Check the handset. If no SMS arrived, the vendor accepted the request but did not")
    print("deliver it, which is a DLT template or sender-ID problem, not a backend one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
