"""HanuOTP SMS delivery.

One implementation behind the existing `OTPDeliveryProvider` interface, shared by every
login channel — Customer, Customer registration, Merchant, Delivery and Admin. No channel has
its own client, and no router or service builds an HTTP request itself.

The code is generated and stored by the existing authentication layer; this module only
carries it to the vendor. It never generates a code, never decides expiry and never changes a
challenge.

**Everything about this request is sensitive.** The URL carries the API key *and* the OTP as
query parameters, so the URL itself is never logged, never attached to an exception and never
stored. Logs carry a masked number and a short reason code, nothing else.
"""

import asyncio
import json
import logging
import re

import httpx

from app.config.app import Settings
from app.shared.otp.provider import (
    OTPDeliveryError,
    OTPDeliveryProvider,
    OTPDeliveryResult,
    mask_for_log,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "hanuotp"

# Identifies this client to the vendor. Sent because an unnamed client is harder for their
# support to trace, and some gateways refuse a request with no User-Agent at all. It does
# **not** get past a JavaScript browser challenge - nothing sent from a server can.
USER_AGENT = "MBGA-Backend/1.0 (+OTP delivery)"

# The vendor expects a bare 10-digit national number; storage keeps the +91 form.
_NATIONAL = re.compile(r"^[6-9]\d{9}$")

# Verified against the live endpoint: every answer is HTTP 200 with
# `{"status": "success"|"error", "message": "..."}`. The HTTP status is therefore never the
# verdict on its own - `status` is.
_FAILURE = "error"

EDGE_BLOCKED = "HANUOTP_BLOCKED_BY_EDGE"

# The endpoint sits behind bot protection that intermittently answers with an HTML
# "Checking your browser" page instead of the API. That is not the vendor rejecting the
# message, so it is reported separately - otherwise an operator hunts for a bad API key when
# the request never reached the API at all.
_HTML_MARKERS = ("<!doctype html", "<html")

# Vendor messages mapped to short, stable reason codes. The vendor's own text is never used as
# the reason: it is free-form, it could grow to echo a parameter, and the reason is written to
# the audit log.
_ERROR_CODES = (
    ("invalid api key", "HANUOTP_INVALID_API_KEY"),
    ("missing required parameter", "HANUOTP_BAD_REQUEST"),
    ("invalid mobile number", "HANUOTP_UNSUPPORTED_NUMBER"),
    ("template", "HANUOTP_TEMPLATE_REJECTED"),
    ("balance", "HANUOTP_INSUFFICIENT_BALANCE"),
    ("insufficient", "HANUOTP_INSUFFICIENT_BALANCE"),
)

# A vendor reference worth keeping is short and opaque. Anything longer is truncated rather
# than stored in full, so an unexpectedly chatty body cannot smuggle content into the database.
_MAX_REFERENCE = 64
_MAX_SANITIZED_BODY = 200


class HanuOTPProvider(OTPDeliveryProvider):
    """Delivers the backend's own OTP through HanuOTP's HTTP endpoint."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        # Settings already refuses an incomplete HanuOTP configuration at startup; this is the
        # second line of defence for a provider built directly in a test or a script.
        missing = [
            name
            for name, value in (
                ("HANUOTP_BASE_URL", settings.hanuotp_base_url),
                ("HANUOTP_API_KEY", settings.hanuotp_api_key),
                ("HANUOTP_TEMPLATE_ID", settings.hanuotp_template_id),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"HanuOTP is not configured: missing {', '.join(missing)}")
        self.base_url = str(settings.hanuotp_base_url)
        if not self.base_url.lower().startswith("https://"):
            raise RuntimeError("HANUOTP_BASE_URL must use https")
        self._api_key = settings.hanuotp_api_key
        self.template_id = settings.hanuotp_template_id
        self.timeout_seconds = settings.hanuotp_timeout_seconds
        self.max_retries = settings.hanuotp_max_retries
        self.edge_block_retries = settings.hanuotp_edge_block_retries
        # Injected by tests and by the smoke script so the transport can be swapped without
        # touching this class.
        self._client = client

    def __repr__(self) -> str:
        # Defined so a stray repr in a log line or a traceback cannot print the key.
        return f"<HanuOTPProvider template={self.template_id!r}>"

    async def send_otp(self, *, mobile_number: str, otp: str, purpose: str, expires_in_seconds: int) -> OTPDeliveryResult:
        national = to_national(mobile_number)
        attempt = 0
        while True:
            attempt += 1
            try:
                reference = await self._dispatch(national=national, otp=otp)
                return OTPDeliveryResult(provider=PROVIDER_NAME, reference=reference)
            except OTPDeliveryError as error:
                logger.warning(
                    "HanuOTP delivery to %s failed (%s, attempt %s)",
                    mask_for_log(mobile_number),
                    error.reason,
                    attempt,
                )
                # A bot-protection page means the vendor never processed the request, so the
                # retry is free. Everything else may already have cost a message.
                budget = self.edge_block_retries if error.reason == EDGE_BLOCKED else self.max_retries
                if not error.retryable or attempt > budget:
                    raise
                await asyncio.sleep(min(0.25 * attempt, 1.0))

    async def _dispatch(self, *, national: str, otp: str) -> str | None:
        # Built as params, never by string concatenation: httpx encodes them, and the key and
        # the code never pass through a format string that something else could log.
        params = {
            "number": national,
            "OTP": otp,
            "apikey": self._api_key,
            "templatesid": self.template_id,
        }
        try:
            headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            if self._client is not None:
                response = await self._client.get(
                    self.base_url, params=params, headers=headers, timeout=self.timeout_seconds
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(self.base_url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise OTPDeliveryError("HANUOTP_TIMEOUT", retryable=True) from exc
        except httpx.TransportError as exc:
            # Connection refused, DNS failure, TLS failure. `from exc` keeps the cause for a
            # traceback; the reason string carries nothing about the request.
            raise OTPDeliveryError("HANUOTP_UNREACHABLE", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise OTPDeliveryError("HANUOTP_REQUEST_FAILED") from exc

        return _interpret(response, national=national, otp=otp, api_key=self._api_key)


def to_national(mobile_number: str) -> str:
    """The 10-digit form the vendor expects, from the stored `+91XXXXXXXXXX`.

    Reuses no second normalisation: the number arriving here has already been validated and
    normalised by the authentication layer. This only strips the country code, and refuses
    anything that does not then look like an Indian mobile number rather than sending a
    malformed number to a paid endpoint.
    """
    national = mobile_number.removeprefix("+91").removeprefix("91") if mobile_number.startswith("+91") else mobile_number
    national = national.strip()
    if not _NATIONAL.match(national):
        raise OTPDeliveryError("HANUOTP_UNSUPPORTED_NUMBER")
    return national


def _interpret(response: httpx.Response, *, national: str, otp: str, api_key: str | None) -> str | None:
    """Sanitise the body, then decide the verdict."""
    return interpret(
        response.status_code,
        _sanitize(response, national=national, otp=otp, api_key=api_key),
    )


def interpret(status_code: int, sanitized_body: str) -> str | None:
    """Decide provider-level success from the vendor's JSON verdict.

    Public so the smoke script reaches the same verdict the authentication flow would, rather
    than carrying a second copy of these rules that could drift from this one.
    """
    if status_code >= 500:
        raise OTPDeliveryError(f"HANUOTP_HTTP_{status_code}", retryable=True)
    if status_code >= 400 and not _looks_like_html(sanitized_body):
        raise OTPDeliveryError(f"HANUOTP_HTTP_{status_code}")
    if _looks_like_html(sanitized_body):
        # A bot-protection page, not the vendor. No message was sent and no charge was made,
        # so this is worth retrying - unlike a vendor rejection, which would fail identically.
        raise OTPDeliveryError(EDGE_BLOCKED, retryable=True)
    if not sanitized_body:
        raise OTPDeliveryError("HANUOTP_EMPTY_RESPONSE")

    try:
        payload = json.loads(sanitized_body)
    except (ValueError, TypeError) as exc:
        raise OTPDeliveryError("HANUOTP_UNRECOGNISED_RESPONSE") from exc
    if not isinstance(payload, dict) or "status" not in payload:
        raise OTPDeliveryError("HANUOTP_UNRECOGNISED_RESPONSE")

    status_value = str(payload.get("status", "")).strip().lower()
    message = str(payload.get("message", "")).strip()
    if status_value == _FAILURE:
        raise OTPDeliveryError(_error_code(message))
    # Anything that is not an explicit failure is a delivery. Checked this way round because
    # the *failure* shape is what was verified against the live endpoint - four different
    # errors, every one of them `status: "error"`. Demanding the exact word "success" instead
    # would turn an unexpected success wording into a 503 for a message that did arrive.
    reference = payload.get("messageId") or payload.get("message_id") or payload.get("id") or message or status_value
    return str(reference)[:_MAX_REFERENCE] or None


def _looks_like_html(body: str) -> bool:
    lowered = body.strip().lower()
    return any(lowered.startswith(marker) or marker in lowered[:200] for marker in _HTML_MARKERS)


def _error_code(message: str) -> str:
    """Map the vendor's free-form message onto one of our own short codes."""
    lowered = message.lower()
    for fragment, code in _ERROR_CODES:
        if fragment in lowered:
            return code
    return "HANUOTP_REJECTED"


def _sanitize(response: httpx.Response, *, national: str, otp: str, api_key: str | None) -> str:
    """A short, secret-free version of the vendor's body, safe to store and print.

    Vendors commonly echo the number and sometimes the message text — which contains the OTP.
    Each secret is replaced before the value goes anywhere, so a stored reference or a smoke
    test printout can never reveal one.
    """
    try:
        text = response.text or ""
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        return ""
    for secret, placeholder in ((api_key, "[apikey]"), (otp, "[otp]"), (national, "[number]")):
        if secret:
            text = text.replace(secret, placeholder)
    # Any remaining run of 4+ digits could still be the code or part of the number.
    text = re.sub(r"\d{4,}", "[redacted]", text)
    return " ".join(text.split())[:_MAX_SANITIZED_BODY]
