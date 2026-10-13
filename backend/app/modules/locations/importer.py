"""Streaming importer for the India Post CSV directory."""

import csv
import re
from datetime import UTC, datetime
from io import TextIOBase
from uuid import uuid4

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.locations.models import PostalLocation

PINCODE = re.compile(r"^\d{6}$")


def _number(value: str | None) -> float | None:
    value = (value or "").strip()
    if not value or value.upper() == "NA":
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def import_postal_csv(
    session: AsyncSession, source: TextIOBase, batch_size: int = 1000
) -> dict[str, int]:
    reader = csv.DictReader(source)
    required = {"pincode", "officename", "district", "statename"}
    if not reader.fieldnames or not required.issubset(
        {name.strip().lower() for name in reader.fieldnames}
    ):
        raise ValueError("CSV header must contain pincode, officename, district and statename.")

    summary = {"processed": 0, "accepted": 0, "invalid": 0}
    batch: list[dict] = []
    dialect = session.bind.dialect.name if session.bind is not None else "mysql"

    async def flush() -> None:
        if not batch:
            return
        if dialect == "mysql":
            statement = mysql_insert(PostalLocation).values(batch)
            statement = statement.on_duplicate_key_update(
                office_type=statement.inserted.office_type,
                delivery_available=statement.inserted.delivery_available,
                district_name=statement.inserted.district_name,
                state_name=statement.inserted.state_name,
                circle_name=statement.inserted.circle_name,
                region_name=statement.inserted.region_name,
                division_name=statement.inserted.division_name,
                latitude=statement.inserted.latitude,
                longitude=statement.inserted.longitude,
                is_active=True,
                updated_at=statement.inserted.updated_at,
            )
        elif dialect == "sqlite":
            statement = sqlite_insert(PostalLocation).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=["pincode", "office_name"],
                set_={
                    key: getattr(statement.excluded, key)
                    for key in (
                        "office_type",
                        "delivery_available",
                        "district_name",
                        "state_name",
                        "circle_name",
                        "region_name",
                        "division_name",
                        "latitude",
                        "longitude",
                        "is_active",
                        "updated_at",
                    )
                },
            )
        else:
            raise RuntimeError(f"Unsupported database dialect for postal import: {dialect}")
        await session.execute(statement)
        await session.commit()
        batch.clear()

    for raw in reader:
        summary["processed"] += 1
        row = {str(key).strip().lower(): value for key, value in raw.items()}
        pincode = (row.get("pincode") or "").strip()
        office = (row.get("officename") or "").strip()
        district = (row.get("district") or "").strip()
        state = (row.get("statename") or "").strip()
        if not PINCODE.fullmatch(pincode) or not office or not district or not state:
            summary["invalid"] += 1
            continue
        now = datetime.now(UTC)
        batch.append(
            {
                "id": str(uuid4()),
                "pincode": pincode,
                "office_name": office,
                "office_type": (row.get("officetype") or "").strip() or None,
                "delivery_available": (row.get("delivery") or "").strip().casefold() == "delivery",
                "district_name": district,
                "state_name": state,
                "circle_name": (row.get("circlename") or "").strip() or None,
                "region_name": (row.get("regionname") or "").strip() or None,
                "division_name": (row.get("divisionname") or "").strip() or None,
                "latitude": _number(row.get("latitude")),
                "longitude": _number(row.get("longitude")),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        summary["accepted"] += 1
        if len(batch) >= batch_size:
            await flush()
    await flush()
    return summary
