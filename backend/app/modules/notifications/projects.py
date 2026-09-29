"""Which Firebase project a device token belongs to.

The three apps are three separate Firebase projects - `mbga-merchant`, `mbga-customer` and
`mbga-delivery-partner` - and **a token is only valid in the project that minted it**. Send
a customer's token through the merchant project and FCM answers `SENDER_ID_MISMATCH`; the
notification is lost and nothing about the token was wrong.

So the routing key is the channel of the session the token was registered on, not who the
notification is addressed to. Those usually agree, but not always: a merchant's owner can
also be a customer, and the same person signed into both apps has two tokens in two
projects. The session knows which is which; the recipient does not.

Each project's client is built once, on first use, and keeps its OAuth token cached. A
channel with no credential configured is skipped and reported rather than failing the pass,
so bringing up one app's push does not wait for the other two.
"""

import logging
from pathlib import Path

from app.config.app import Settings
from app.modules.authentication.constants import LoginChannel
from app.modules.notifications.fcm import FcmClient, FcmCredentials

logger = logging.getLogger(__name__)


class FcmProjects:
    """One FCM client per app, resolved by the channel a token was registered on."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._clients: dict[str, FcmClient | None] = {}
        #: Channels already reported as unconfigured, so the log says it once rather than
        #: once per undeliverable row.
        self._warned: set[str] = set()

    def credential_path(self, channel: str) -> str | None:
        """The configured key file for one channel, or None.

        Falls back to `fcm_credentials_file` so a single-project deployment - which is what
        this was before the customer and delivery apps got their own - keeps working with
        no configuration change.
        """
        per_channel = {
            LoginChannel.MERCHANT.value: self.settings.fcm_credentials_merchant,
            LoginChannel.CUSTOMER.value: self.settings.fcm_credentials_customer,
            LoginChannel.DELIVERY.value: self.settings.fcm_credentials_delivery,
        }
        return per_channel.get((channel or "").upper()) or self.settings.fcm_credentials_file or None

    def client_for(self, channel: str) -> FcmClient | None:
        """The client for this channel, or None when it has no usable credential."""
        key = (channel or "").upper()
        if key in self._clients:
            return self._clients[key]

        path = self.credential_path(key)
        client = None
        if path:
            resolved = Path(path)
            if not resolved.is_absolute():
                resolved = Path(__file__).resolve().parents[3] / resolved
            try:
                credentials = FcmCredentials(resolved)
                client = FcmClient(credentials)
                logger.info("FCM %s -> project %s", key or "?", credentials.project_id)
            except (OSError, ValueError) as error:
                self._warn(key, f"{resolved}: {error}")
        else:
            self._warn(key, "no credential configured")
        self._clients[key] = client
        return client

    def _warn(self, channel: str, detail: str) -> None:
        if channel in self._warned:
            return
        self._warned.add(channel)
        logger.warning("Push is not configured for the %s app (%s); its rows stay queued.", channel, detail)

    def configured(self) -> dict[str, str]:
        """`{channel: project_id}` for every app that can currently send.

        Used by the worker to print what it is set up for, so a misconfiguration is visible
        before anybody waits for a notification that was never going anywhere.
        """
        ready = {}
        for channel in (LoginChannel.MERCHANT, LoginChannel.CUSTOMER, LoginChannel.DELIVERY):
            client = self.client_for(channel.value)
            if client is not None:
                ready[channel.value] = client.credentials.project_id
        return ready

    async def aclose(self) -> None:
        for client in self._clients.values():
            if client is not None:
                await client.aclose()
        self._clients.clear()
