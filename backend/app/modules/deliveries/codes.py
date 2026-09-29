"""The proof-of-delivery code (spec §10.4).

Four digits, generated when the van leaves, read out by the customer at the gate, checked when
the driver confirms the handover. It is the difference between "the driver says it was
delivered" and "the customer says it was received".

Two decisions worth stating, because both are easy to get wrong in a way nobody notices:

**It is hashed, never stored in the clear.** A plain column would be a live shared secret that
anybody with table access could read off and use to confirm a delivery that never happened.

**It does not go through the login OTP tables.** Those carry per-IP and per-number throttles
sized for sign-in abuse. A driver at a noisy gate retrying a digit the customer misread would
eat into that budget and could lock the customer out of their own app - punishing the customer
for the driver's hearing. So the code lives on the slip with its own attempt counter.
"""

import secrets

from app.modules.authentication.password_hasher import hash_secret, verify_secret
from app.modules.deliveries.constants import CODE_LENGTH, MOCK_CODE


def generate() -> str:
    """A fresh code. `secrets`, not `random`: this authorises a handover."""
    upper_bound = 10**CODE_LENGTH
    return f"{secrets.randbelow(upper_bound):0{CODE_LENGTH}d}"


def fingerprint(code: str) -> str:
    return hash_secret(code)


def matches(submitted: str, stored_hash: str | None, *, allow_mock: bool) -> bool:
    """Whether this code confirms the slip.

    `allow_mock` honours the spec's "mock accepts 4321", and is wired to the same setting that
    already exposes login OTPs in responses - so it is on locally and off in production. It is
    passed in rather than read from settings here to keep this module free of configuration and
    directly testable both ways.
    """
    if not stored_hash:
        return False
    if allow_mock and secrets.compare_digest(submitted, MOCK_CODE):
        return True
    return verify_secret(submitted, stored_hash)


def is_well_formed(code: str | None) -> bool:
    """Four digits. Checked before hashing, so a letter never costs a verification attempt."""
    return bool(code) and len(code) == CODE_LENGTH and code.isdigit()
