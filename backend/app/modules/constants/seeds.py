"""Seeds the `constants` table, and keeps it honest.

Rows are written **from the code enums the validators use**, not typed in by hand. That is
the whole safety property: the endpoint can never offer the app a choice the write endpoints
would reject, because both sides read the same source.

An operator may reword a `const_value` freely - that is the point of putting labels in a
table. Changing a `const_key` breaks the contract with the API, so the seeder restores it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.constants.models import Constant
from app.modules.customers.constants import CustomerType, KycDocumentType, PricingTier

# Group names the app filters on.
CUSTOMER_TYPES = "customerTypes"
DOCUMENT_TYPES = "documentTypes"
PRICING_TIERS = "pricingTiers"
STATES = "states"

DELIVERY_STATES = ("Madhya Pradesh", "Maharashtra", "Rajasthan", "Gujarat", "Uttar Pradesh", "Chhattisgarh")


@dataclass(frozen=True)
class SeedConstant:
    group: str
    key: str
    value: str
    sort_order: int


def seed_rows() -> list[SeedConstant]:
    """Every row the table should contain, derived from the enums."""
    labels = {
        CustomerType.RETAIL: "Retail",
        CustomerType.INDUSTRIAL: "Industrial",
        KycDocumentType.AADHAAR: "Aadhaar Card",
        KycDocumentType.PAN: "PAN Card",
        KycDocumentType.FSSAI: "FSSAI Licence",
        KycDocumentType.GST: "GST Certificate",
        PricingTier.STANDARD: "Standard",
        PricingTier.BULK: "Bulk",
        PricingTier.KEY_ACCOUNT: "Key Account",
    }
    rows: list[SeedConstant] = []
    for group, members in (
        (CUSTOMER_TYPES, list(CustomerType)),
        (DOCUMENT_TYPES, list(KycDocumentType)),
        (PRICING_TIERS, list(PricingTier)),
    ):
        rows += [SeedConstant(group, member.value, labels[member], order) for order, member in enumerate(members)]
    rows += [SeedConstant(STATES, name, name, order) for order, name in enumerate(DELIVERY_STATES)]
    return rows


class ConstantsSeedRunner:
    """Inserts missing rows. Idempotent, and never overwrites an edited label."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> dict[str, int]:
        existing = {
            row.const_key: row
            for row in await self.session.scalars(select(Constant))
        }
        now = datetime.now(UTC)
        created = repaired = 0
        for seed in seed_rows():
            row = existing.get(seed.key)
            if row is None:
                self.session.add(
                    Constant(
                        id=str(uuid4()),
                        const_key=seed.key,
                        const_value=seed.value,
                        const_group=seed.group,
                        sort_order=seed.sort_order,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1
                continue
            # A reworded label is left alone; a moved row is put back, because the group is
            # what the app filters on and a wrong one hides the option from its dropdown.
            if row.const_group != seed.group:
                row.const_group = seed.group
                row.updated_at = now
                repaired += 1
        await self.session.commit()
        return {"constants_created": created, "constants_repaired": repaired}
