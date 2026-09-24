from fastapi import status

from app.shared.exceptions.api_error import ApiError


class AuthorizationDeniedError(ApiError):
    def __init__(self, code: str = "PERMISSION_DENIED") -> None:
        super().__init__(code, status.HTTP_403_FORBIDDEN)


class UnauthenticatedError(ApiError):
    def __init__(self, code: str = "AUTH_REQUIRED") -> None:
        super().__init__(code, status.HTTP_401_UNAUTHORIZED)
