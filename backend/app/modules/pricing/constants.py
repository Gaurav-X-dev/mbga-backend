"""Pricing vocabularies: cylinder types, tiers, month statuses and the opening rate card.

The cylinder type is the authority for what the API accepts, so it lives in code next to the
validators rather than in the `constants` table - the same rule `modules/constants/models.py`
states for customer and document types.

`tier` is kept as a *validated string set* rather than reusing
`customers.constants.PricingTier`. That enum is the customer's own account tier and is
already published to the apps through the `pricingTiers` dropdown; adding PREFERRED to it
would offer staff an account tier nothing else understands. Only STANDARD is populated
today (spec "Scope"), but the column and the API accept all four so Preferred and Key
Account can be switched on without a migration.
"""

from decimal import Decimal
from enum import StrEnum


class CylinderType(StrEnum):
    LPG_5KG = "LPG_5KG"
    LPG_19KG = "LPG_19KG"
    LPG_47_5KG_L = "LPG_47_5KG_L"
    LPG_47_5KG_V = "LPG_47_5KG_V"
    LPG_422KG_HIPPO = "LPG_422KG_HIPPO"


CYLINDER_LABELS: dict[CylinderType, str] = {
    CylinderType.LPG_5KG: "5 KG Cylinder",
    CylinderType.LPG_19KG: "19 KG Cylinder",
    CylinderType.LPG_47_5KG_L: "47.5 KG Cylinder (Liquid)",
    CylinderType.LPG_47_5KG_V: "47.5 KG Cylinder (Vapour)",
    CylinderType.LPG_422KG_HIPPO: "422 KG Hippo",
}

# Hippo is industrial-only (spec §4, "same eligibility rule as order creation"). Every other
# type is offered to both customer types. Order creation will read this same mapping when it
# lands, so the Price Setting tab and the order form cannot disagree about what is orderable.
INDUSTRIAL_ONLY_CYLINDERS: frozenset[CylinderType] = frozenset({CylinderType.LPG_422KG_HIPPO})


def cylinders_for(customer_type: str | None) -> list[CylinderType]:
    """The cylinder types this customer may be priced for, in display order."""
    if (customer_type or "").upper() == "INDUSTRIAL":
        return list(CylinderType)
    return [kind for kind in CylinderType if kind not in INDUSTRIAL_ONLY_CYLINDERS]


class PricingTier(StrEnum):
    """Tiers the pricing tables accept. Only STANDARD is populated today."""

    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    KEY_ACCOUNT = "KEY_ACCOUNT"
    BULK = "BULK"


#: The one tier the screens read and the seeder populates.
ACTIVE_TIER = PricingTier.STANDARD


class PricingMonthStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"


#: A month in this state is read-only; editing an entry inside it is a 409.
CLOSED_MONTH_STATUSES: frozenset[str] = frozenset({PricingMonthStatus.ARCHIVED.value})


class OverrideAction(StrEnum):
    SET = "SET"
    UPDATE = "UPDATE"
    REMOVE = "REMOVE"


DEFAULT_GST_PERCENT = Decimal("18.00")

# The rate card a merchant's first pricing month opens with, from the spec's own example.
# Every later month carries the previous month's rates forward instead of using these, so
# these numbers are only ever the very first thing a new merchant sees - and staff change
# them through the mid-month endpoint like any other rate.
DEFAULT_STANDARD_RATES: dict[CylinderType, tuple[Decimal, Decimal]] = {
    CylinderType.LPG_5KG: (Decimal("445.00"), Decimal("45.00")),
    CylinderType.LPG_19KG: (Decimal("1690.00"), Decimal("110.00")),
    CylinderType.LPG_47_5KG_L: (Decimal("4225.00"), Decimal("275.00")),
    CylinderType.LPG_47_5KG_V: (Decimal("4260.00"), Decimal("275.00")),
    CylinderType.LPG_422KG_HIPPO: (Decimal("37550.00"), Decimal("1450.00")),
}
