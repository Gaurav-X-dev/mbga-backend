from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.DELIVERY, "DELIVERY_LOGIN"))


@router.get("/login-channel")
async def login_channel() -> dict[str, LoginChannel]:
    return {"login_channel": LoginChannel.DELIVERY}
