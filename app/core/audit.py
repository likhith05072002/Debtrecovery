"""Audit logging service — records all significant user actions.

Provides an immutable, append-only audit trail for:
- SOC 2 compliance
- CFPB audit readiness
- Internal security monitoring
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.webhook import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    changes: dict | None = None,
    metadata: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log an auditable action.

    Args:
        db: Database session
        org_id: Organization ID
        user_id: User performing the action (None for system actions)
        action: Action identifier (e.g. "borrower.created", "campaign.started")
        resource_type: Type of resource affected
        resource_id: ID of the specific resource
        changes: Dict of field changes {field: {old: x, new: y}}
        metadata: Additional context
        request: FastAPI request for IP/UA extraction
    """
    ip_address = None
    user_agent = None
    if request:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

    entry = AuditLog(
        organization_id=org_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
        metadata=metadata,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    return entry


# Convenience functions for common actions
async def log_create(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    resource_type: str, resource_id: uuid.UUID, request: Request | None = None,
) -> AuditLog:
    return await log_action(
        db, org_id=org_id, user_id=user_id,
        action=f"{resource_type}.created",
        resource_type=resource_type, resource_id=resource_id,
        request=request,
    )


async def log_update(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    resource_type: str, resource_id: uuid.UUID,
    changes: dict, request: Request | None = None,
) -> AuditLog:
    return await log_action(
        db, org_id=org_id, user_id=user_id,
        action=f"{resource_type}.updated",
        resource_type=resource_type, resource_id=resource_id,
        changes=changes, request=request,
    )


async def log_delete(
    db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID,
    resource_type: str, resource_id: uuid.UUID, request: Request | None = None,
) -> AuditLog:
    return await log_action(
        db, org_id=org_id, user_id=user_id,
        action=f"{resource_type}.deleted",
        resource_type=resource_type, resource_id=resource_id,
        request=request,
    )
