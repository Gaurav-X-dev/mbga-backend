"""The Perione e-Way Bill transport.

A second provider API, separate from the e-invoice one: its own path
(`/ewaybillapi/v1.03/...`), its own `PEWAYS` credentials and its own payload vocabulary. It
is used for the one case the e-invoice call cannot cover - a consignment over the threshold
sold to a customer with no GST registration, where there is no IRN for the bill to live
inside.

**Authentication is best-effort on purpose.** The e-invoice API hands back an `AuthToken`
that every later call must carry. This one's `authenticate` answers `status_cd: 1` and
echoes the headers back without a token, and the provider's own sample `genewaybill` call
sends no `auth-token` header at all - the bearer token and the client pair are the whole
credential. So a token is sent when the provider gives one and the call proceeds without it
when it does not, rather than failing on a step this API may not have.

**Never raises for a rejection**, for the same reason `PerioneClient` does not: a portal
that says "Vehicle number is invalid" has answered, and turning that into an exception would
have the worker retry bad data forever.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.einvoice.client import REQUEST_TIMEOUT_SECONDS, TOKEN_REFRESH_MARGIN_SECONDS, _message, _text

logger = logging.getLogger(__name__)

#: The portal's "this document already has an e-Way Bill". Like the duplicate-IRN codes, it
#: is the portal saying the work is done rather than that anything went wrong.
DUPLICATE_EWAY_CODES = {"604", "assigned"}


@dataclass(slots=True)
class EwayResult:
    """What came back from one `genewaybill` attempt."""

    ok: bool = False
    eway_bill_number: str | None = None
    eway_bill_date: str | None = None
    valid_till: str | None = None
    #: The portal's own words, kept for the operator who has to act on them.
    error: str | None = None
    #: True when trying again later could succeed - a timeout, a 5xx, an expired token.
    retryable: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class PerioneEwayClient:
    """One merchant's connection to the e-Way Bill API."""

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
        version: str = "v1.03",
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
        self.version = version
        self._http = http or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_http = http is None
        self._auth_token: str | None = None
        self._auth_expires_at: float = 0.0

    @property
    def _root(self) -> str:
        return f"{self.base_url}/ewaybillapi/{self.version}"

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "*/*",
            "ip_address": self.ip_address,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "gstin": self.gstin,
            "Authorization": f"Bearer {self.bearer_token}",
        }

    async def auth_token(self) -> str | None:
        """A cached portal token, or None when this API does not issue one.

        None is an ordinary answer here, not a failure - see the module docstring.
        """
        if self._auth_token and time.time() < self._auth_expires_at:
            return self._auth_token

        response = await self._http.get(
            f"{self._root}/authenticate",
            params={
                "email": self.email,
                "username": self.username,
                "password": self.password,
            },
            headers=self._base_headers(),
        )
        response.raise_for_status()
        body = response.json()
        if str(body.get("status_cd")) not in ("1", "Sucess", "Success"):
            raise RuntimeError(f"The provider refused the e-Way Bill credentials: {_message(body)}")

        data = body.get("data") or {}
        token = data.get("authtoken") or data.get("AuthToken") or data.get("authToken")
        if not token:
            return None

        self._auth_token = str(token)
        # The e-invoice API states an absolute expiry; this one may state a lifetime in
        # seconds or nothing at all. An unreadable value falls back to a short cache rather
        # than wedging the worker.
        self._auth_expires_at = time.time() + 600 - TOKEN_REFRESH_MARGIN_SECONDS
        return self._auth_token

    async def generate(self, payload: dict[str, Any]) -> EwayResult:
        """Raise one e-Way Bill. The outcome is the return value, never an exception."""
        try:
            token = await self.auth_token()
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            # Authentication is infrastructure, not document data: always worth retrying.
            return EwayResult(error=f"Could not authenticate with the provider: {error}", retryable=True)

        headers = {**self._base_headers(), "Content-Type": "application/json"}
        if token:
            headers["auth-token"] = token

        try:
            response = await self._http.post(
                f"{self._root}/ewayapi/genewaybill",
                params={"email": self.email},
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as error:
            return EwayResult(error=f"Could not reach the provider: {error}", retryable=True)

        try:
            body = response.json()
        except ValueError:
            return EwayResult(
                error=f"The provider returned {response.status_code} with a non-JSON body.",
                retryable=response.status_code >= 500,
                raw={"status": response.status_code, "text": response.text[:2000]},
            )

        if response.status_code >= 500:
            return EwayResult(error=_message(body), retryable=True, raw=body)

        number = _eway_number(body)
        if number:
            data = body.get("data") or {}
            return EwayResult(
                ok=True,
                eway_bill_number=number,
                eway_bill_date=_text(data.get("ewayBillDate") or data.get("EwbDt")),
                valid_till=_text(data.get("validUpto") or data.get("EwbValidTill")),
                raw=body,
            )

        message = _message(body)
        expired = "token" in message.lower() and "expir" in message.lower()
        if expired:
            self._auth_token = None
        return EwayResult(error=message, retryable=expired, raw=body)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


def _eway_number(body: dict[str, Any]) -> str | None:
    """The bill number, whether the portal accepted it now or had already issued it.

    Providers spell the field differently depending on which of the two happened, so the
    likely names are tried rather than one being assumed.
    """
    data = body.get("data")
    candidates: list[dict[str, Any]] = []
    if isinstance(data, dict):
        candidates = [data]
    elif isinstance(data, list):
        candidates = [item for item in data if isinstance(item, dict)]

    for item in candidates:
        for key in ("ewayBillNo", "ewbNo", "EwbNo", "ewayBillNumber"):
            value = item.get(key)
            if value:
                return str(value)
    return None
