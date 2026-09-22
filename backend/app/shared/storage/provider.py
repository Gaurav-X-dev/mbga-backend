"""Storage-provider interface for uploaded document files.

No vendor is chosen here. Production will bind a provider that issues its own signed URLs;
until then the local provider below keeps files on a private disk path and the application
signs a short-lived token for its own streaming endpoint. Swapping providers must not change
any route, so the interface is the only thing business code depends on.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    """What a provider returns once bytes are safely at rest."""

    storage_key: str
    size: int
    checksum_sha256: str


class StorageProvider(ABC):
    """A place to put a file and get it back. Keys are opaque to callers."""

    name: str = "abstract"

    @abstractmethod
    async def save(self, key: str, chunks) -> StoredObject:
        """Consume an async iterator of byte chunks and store them under `key`."""

    @abstractmethod
    def open(self, key: str):
        """Return an async iterator over the object's bytes.

        Synchronous on purpose, so a provider validates the key before the caller starts
        streaming rather than during it.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object. Missing objects are not an error."""

    def signed_url(self, key: str, *, expires_in: int) -> str | None:
        """A provider-native time-limited URL, or None when the provider has none.

        Returning None is the documented signal that the caller must fall back to the
        application's own signed-token streaming endpoint.
        """
        return None
