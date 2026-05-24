"""Role-based access control (RBAC) for the application.

Role hierarchy: owner > admin > manager > agent > readonly
"""
from __future__ import annotations

from enum import IntEnum
from functools import wraps
from typing import Callable

from fastapi import HTTPException, status


class Role(IntEnum):
    """Role hierarchy — higher value = more permissions."""
    READONLY = 0
    AGENT = 1
    MANAGER = 2
    ADMIN = 3
    OWNER = 4


ROLE_MAP: dict[str, Role] = {
    "readonly": Role.READONLY,
    "agent": Role.AGENT,
    "manager": Role.MANAGER,
    "admin": Role.ADMIN,
    "owner": Role.OWNER,
}


def get_role_level(role_str: str) -> Role:
    """Convert role string to Role enum."""
    return ROLE_MAP.get(role_str.lower(), Role.READONLY)


def check_permission(user_role: str, required_role: str) -> bool:
    """Check if user_role meets or exceeds required_role."""
    return get_role_level(user_role) >= get_role_level(required_role)


def require_role(minimum_role: str):
    """FastAPI dependency factory that enforces a minimum role.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(...): ...

    Or as a direct check in endpoint body via the returned dependency.
    """
    from app.dependencies import get_current_user  # deferred import to avoid circular

    async def _check_role(current_user=None):
        # This is used as a dependency that receives the current user
        # The actual enforcement happens in the endpoint via get_current_user
        pass

    def dependency(current_user):
        if not check_permission(current_user.role, minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum_role} role or higher",
            )
        return current_user

    return dependency


def enforce_role(user_role: str, minimum_role: str) -> None:
    """Raise 403 if user doesn't have the required role. Use in endpoint bodies."""
    if not check_permission(user_role, minimum_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {minimum_role} role or higher",
        )
