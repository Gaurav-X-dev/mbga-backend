"""The Perione e-invoice transport.

Two calls, in order: `authenticate` hands back an `AuthToken` with an expiry, and `GENERATE`
sends the document under that token. The token is cached, because asking for a fresh one per
invoice is both slow and something providers rate-limit.

**Never raises for a rejection.** A portal that says "Buyer GSTIN is invalid" has answered
the question; an exception would turn an answer into an outage and the worker would retry
bad data forever. Outcomes come back as `GenerateResult`, which separates the two things the
caller has to tell apart - *try this again later* and *this will never work until somebody
edits it* - because treating a network blip as a permanent rejection abandons an invoice
that was fine, and treating a rejection as a blip retries it five times for nothing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: The portal is slow under load; a tight timeout turns a success into a retry, and a retry
#: of a GENERATE that actually succeeded is a duplicate-IRN rejection.
REQUEST_TIMEOUT_SECONDS = 60.0

#: Re-authenticate this long before the token expires, rather than discovering mid-batch.
TOKEN_REFRESH_MARGIN_SECONDS = 300

#: NIC's "this document already has an IRN". Not a failure: the portal is telling us the
#: work is done, and the IRN it quotes is the one we should have stored.
DUPLICATE_IRN_CODES = {"2150", "2172"}


@dataclass(slots=True)
class GenerateResult:
    """What came back from one GENERATE attempt."""

    ok: bool = False
    #: Set when the portal accepted the document, or told us it already had.
    irn: str | None = None
    acknowledgement_number: str | None = None
    acknowledgement_date: str | None = None
    eway_bill_number: str | None = None
    eway_bill_date: str | None = None
    eway_bill_valid_till: str | None = None
    signed_qr_code: str | None = None
    #: The portal's own words, kept for the operator who has to act on them.
    error: str | None = None
    #: True when trying again later could succeed - a timeout, a 5xx, an expired token.
    #: False means the document itself is wrong and retrying changes nothing.
    retryable: bool = False
    #: The raw response, for reconciling against the portal's own records.
    raw: dict[str, Any] = field(default_factory=dict)


class PerioneClient:
    """One merchant's connection to the e-invoice provider."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        username: str,
        password: str,
        client_id: str,
        client_secret: str,
        bearer_token: str,
        gstin: str,
        ip_address: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.bearer_token = bearer_token
        self.gstin = gstin
        self.ip_address = ip_address
        self._http = http or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_http = http is None
        self._auth_token: str | None = None
        self._auth_expires_at: float = 0.0

    # --- transport ---------------------------------------------------------------------

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "*/*",
            "username": self.username,
            "ip_address": self.ip_address,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "gstin": self.gstin,
            "Authorization": f"Bearer {self.bearer_token}",
        }

    async def auth_token(self) -> str:
        """A cached portal token, refreshed shortly before it expires."""
        if self._auth_token and time.time() < self._auth_expires_at:
            return self._auth_token

        headers = {**self._base_headers(), "password": self.password}
        response = await self._http.get(
            f"{self.base_url}/einvoice/authenticate",
            params={"email": self.email},
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") or {}
        token = data.get("AuthToken")
        if not token:
            raise RuntimeError(f"The provider returned no AuthToken: {body.get('status_desc') or body}")

        self._auth_token = str(token)
        # The provider states an absolute expiry rather than a lifetime. Parsing it is
        # better than assuming six hours, but a malformed value must not wedge the worker,
        # so an unreadable expiry falls back to a short cache.
        self._auth_expires_at = _expiry_epoch(data.get("TokenExpiry")) - TOKEN_REFRESH_MARGIN_SECONDS
        if self._auth_expires_at <= time.time():
            self._auth_expires_at = time.time() + 600
        return self._auth_token

    async def generate(self, payload: dict[str, Any], *, version: str = "V1_03") -> GenerateResult:
        """Send one document. The outcome is the return value, never an exception."""
        try:
            token = await self.auth_token()
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            # Authentication is infrastructure, not document data: always worth retrying.
            return GenerateResult(error=f"Could not authenticate with the provider: {error}", retryable=True)

        headers = {
            **self._base_headers(),
            "auth-token": token,
            "Content-Type": "application/json",
        }
        try:
            response = await self._http.post(
                f"{self.base_url}/einvoice/type/GENERATE/version/{version}",
                params={"email": self.email},
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as error:
            # The request may or may not have reached the portal. It is retryable, and a
            # duplicate-IRN answer on the retry is handled as a success below - which is
            # exactly why that case is not treated as an error.
            return GenerateResult(error=f"Could not reach the provider: {error}", retryable=True)

        try:
            body = response.json()
        except ValueError:
            return GenerateResult(
                error=f"The provider returned {response.status_code} with a non-JSON body.",
                retryable=response.status_code >= 500,
                raw={"status": response.status_code, "text": response.text[:2000]},
            )

        if response.status_code >= 500:
            return GenerateResult(error=_message(body), retryable=True, raw=body)

        data = body.get("data")
        if isinstance(data, dict) and data.get("Irn"):
            return _accepted(data, body)

        # A duplicate is the portal telling us this document already has an IRN. The work is
        # done; recording the IRN it quotes is the correct outcome, not an error to show.
        duplicate = _duplicate_irn(body)
        if duplicate:
            return GenerateResult(ok=True, irn=duplicate, error=None, raw=body)

        # Anything else is the portal rejecting the document. A token that expired between
        # the cache check and the call is the one rejection worth retrying.
        message = _message(body)
        expired = "token" in message.lower() and "expir" in message.lower()
        if expired:
            self._auth_token = None
        return GenerateResult(error=message, retryable=expired, raw=body)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


def _accepted(data: dict[str, Any], body: dict[str, Any]) -> GenerateResult:
    return GenerateResult(
        ok=True,
        irn=str(data.get("Irn")),
        acknowledgement_number=_text(data.get("AckNo")),
        acknowledgement_date=_text(data.get("AckDt")),
        eway_bill_number=_text(data.get("EwbNo")),
        eway_bill_date=_text(data.get("EwbDt")),
        eway_bill_valid_till=_text(data.get("EwbValidTill")),
        signed_qr_code=_text(data.get("SignedQRCode")),
        raw=body,
    )


def _text(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _message(body: dict[str, Any]) -> str:
    """The most useful sentence in a rejection.

    Providers nest the portal's error list differently depending on where it failed, so the
    likely places are tried in turn rather than assuming one shape.
    """
    for key in ("status_desc", "message", "error", "errorMessage"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    data = body.get("data")
    if isinstance(data, list) and data:
        return json.dumps(data)[:500]
    if isinstance(data, dict):
        for key in ("ErrorDetails", "errorDetails", "message"):
            value = data.get(key)
            if value:
                return json.dumps(value)[:500]
    return json.dumps(body)[:500]


def _duplicate_irn(body: dict[str, Any]) -> str | None:
    """The IRN quoted back when the portal says this document already has one."""
    data = body.get("data")
    candidates: list[dict[str, Any]] = []
    if isinstance(data, list):
        candidates = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        candidates = [data]
    for item in candidates:
        code = str(item.get("ErrorCode") or item.get("errorCode") or "")
        if code not in DUPLICATE_IRN_CODES:
            continue
        description = item.get("Desc")
        irn = (
            item.get("Irn")
            or item.get("irn")
            or (description.get("Irn") if isinstance(description, dict) else None)
        )
        if irn:
            return str(irn)
    return None


def _expiry_epoch(value: object | None) -> float:
    """`2026-10-23 17:04:39` in IST, as an epoch second."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not value:
        return 0.0
    try:
        moment = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        logger.warning("Unreadable TokenExpiry from the e-invoice provider: %r", value)
        return 0.0
    return moment.replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
