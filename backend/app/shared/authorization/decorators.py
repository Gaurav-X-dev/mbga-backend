from fastapi import Depends

from app.shared.authorization.dependencies import require_permission


def permission_required(permission: str) -> Depends:
    return Depends(require_permission(permission))
