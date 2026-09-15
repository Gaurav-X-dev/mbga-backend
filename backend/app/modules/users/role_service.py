from app.modules.users.role_repository import UserRoleRepository


class UserRoleService:
    def __init__(self, repository: UserRoleRepository) -> None:
        self.repository = repository

    async def assign_role(self, *, user_id: str, role_id: str, actor_user_id: str) -> None:
        if user_id == actor_user_id:
            from app.shared.authorization.exceptions import AuthorizationDeniedError

            raise AuthorizationDeniedError("Users cannot assign roles to themselves")
        # TODO: Persist idempotent assignment inside a transaction after RBAC model review.
        return None
