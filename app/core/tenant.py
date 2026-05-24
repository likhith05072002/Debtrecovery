"""Multi-tenancy context middleware.

Provides organization-scoped database queries by injecting org_id filtering
into SQLAlchemy sessions via FastAPI dependencies.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

# Context variable holding the current tenant for the request lifecycle
_current_tenant: ContextVar[uuid.UUID | None] = ContextVar("current_tenant", default=None)


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context for the current request."""
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str


def set_current_tenant(org_id: uuid.UUID) -> None:
    """Set the current tenant for this request context."""
    _current_tenant.set(org_id)


def get_current_tenant() -> uuid.UUID | None:
    """Get the current tenant from context. Returns None if not set."""
    return _current_tenant.get()


def require_current_tenant() -> uuid.UUID:
    """Get the current tenant, raising if not set."""
    tenant = _current_tenant.get()
    if tenant is None:
        raise RuntimeError("No tenant context set for current request")
    return tenant
