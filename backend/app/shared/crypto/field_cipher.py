"""Reversible encryption for a single database column, plus a keyed lookup hash.

Why both: a KYC identifier has to be *retrievable* by an authorised reviewer, so it is
encrypted rather than hashed. But duplicate detection needs an equality test, and
ciphertext differs on every write because Fernet uses a random IV — so an equality-searchable
value is derived separately.

That derived value is an **HMAC**, not a plain digest. Aadhaar has only 10^12 possible values
and PAN even fewer patterns; an unkeyed SHA-256 of either is brute-forced in seconds, so a
leaked column would be as good as plaintext. Keying it means the attacker also needs the
secret, which never leaves the application.
"""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class FieldCipher:
    """Encrypts and decrypts one class of field with a key derived from the app secret."""

    def __init__(self, secret: str, *, purpose: str = "kyc-document-number") -> None:
        # A per-purpose key, so a cipher built for one column cannot read another's rows.
        material = hashlib.sha256(f"{purpose}:{secret}".encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(material))
        self._mac_key = hashlib.sha256(f"{purpose}:lookup:{secret}".encode()).digest()

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str | None:
        """Returns None for a value this key cannot read, rather than raising.

        A rotated or mismatched secret must not turn a whole list endpoint into a 500; the
        caller renders the masked value it already stored instead.
        """
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def lookup_hash(self, value: str) -> str:
        """A stable, equality-searchable digest of `value`. Not reversible."""
        return keyed_lookup_hash(self._mac_key, value)


def keyed_lookup_hash(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
