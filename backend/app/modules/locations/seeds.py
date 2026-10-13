"""The delivery area the agency starts with.

Haryana and its districts, because that is where the agency runs today. More states are added
from the panel, or by extending this list and re-running the seeder - it inserts what is
missing and leaves edited names alone, the same rule the constants seeder follows.

District names, not every town: an address form needs the places a round actually reaches, and
a list of nine hundred villages is a list nobody scrolls.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedState:
    code: str
    name: str
    cities: tuple[str, ...]


#: Haryana's districts, alphabetical. The order a dropdown shows them in is this one.
HARYANA_CITIES = (
    "Ambala",
    "Bhiwani",
    "Charkhi Dadri",
    "Faridabad",
    "Fatehabad",
    "Gurugram",
    "Hisar",
    "Jhajjar",
    "Jind",
    "Kaithal",
    "Karnal",
    "Kurukshetra",
    "Mahendragarh",
    "Nuh",
    "Palwal",
    "Panchkula",
    "Panipat",
    "Rewari",
    "Rohtak",
    "Sirsa",
    "Sonipat",
    "Yamunanagar",
)

SEED_STATES: tuple[SeedState, ...] = (SeedState("HR", "Haryana", HARYANA_CITIES),)


def slugify(name: str) -> str:
    """The stable identity under a city's name: lower case, spaces and dots to hyphens."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
