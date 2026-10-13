"""Platform administration of the postal directory."""

import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.locations.importer import import_postal_csv
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

router = APIRouter(prefix="/postal-locations", tags=["Admin Postal Locations"])
guards = [
    Depends(require_login_channel(LoginChannel.ADMIN)),
    Depends(require_permission("platform_settings.manage")),
]


@router.post("/import", dependencies=guards, summary="Import or refresh the India Post CSV")
async def import_csv(
    upload: Annotated[UploadFile, File(description="India Post CSV file")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, int]:
    if not (upload.filename or "").lower().endswith(".csv"):
        raise ApiError(
            "INVALID_FILE_TYPE", status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload a CSV file."
        )
    wrapper = io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline="")
    try:
        return await import_postal_csv(session, wrapper)
    except (UnicodeDecodeError, ValueError) as exc:
        await session.rollback()
        raise ApiError(
            "INVALID_POSTAL_CSV", status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    finally:
        wrapper.detach()
