from fastapi import HTTPException, status


class RoleAlreadyExistsError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail="Role code already exists")


class ProtectedSystemRoleError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail="System role is protected")


class LastSuperAdminError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail="Last active Super Admin is protected")
