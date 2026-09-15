from app.modules.authentication.schemas import DeviceInfo


class SessionService:
    async def create_login_session(self, *, user_id: str, device: DeviceInfo | None) -> str:
        # TODO: Persist login session and device metadata after auth model review.
        return f"pending-session-for-{user_id}"

    async def revoke_session(self, *, session_id: str) -> None:
        # TODO: Revoke one refresh-token session.
        return None

    async def revoke_all_sessions(self, *, user_id: str) -> None:
        # TODO: Revoke all refresh-token sessions for user.
        return None
