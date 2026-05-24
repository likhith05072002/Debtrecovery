"""Audit log endpoints — read-only access to the immutable audit trail."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import enforce_role
from app.dependencies import get_current_user, get_db
from app.models.database.user import User
from app.models.database.webhook import AuditLog

router = APIRouter()


class AuditLogEntry(BaseModel):
    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    changes: dict | None
    ip_address: str | None
    created_at: str


@router.get("", response_model=list[AuditLogEntry])
async def list_audit_log(
    resource_type: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    user_id: Optional[uuid.UUID] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    skip: int = 0,
    limit: int = Query(default=100, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List audit log entries. Requires admin+ role. Immutable, append-only."""
    enforce_role(current_user.role, "admin")

    query = (
        select(AuditLog)
        .where(AuditLog.organization_id == current_user.organization_id)
        .order_by(AuditLog.created_at.desc())
    )

    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if from_date:
        query = query.where(AuditLog.created_at >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query = query.where(AuditLog.created_at <= datetime.combine(to_date, datetime.max.time()))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)

    return [
        AuditLogEntry(
            id=str(e.id),
            user_id=str(e.user_id) if e.user_id else None,
            action=e.action,
            resource_type=e.resource_type,
            resource_id=str(e.resource_id) if e.resource_id else None,
            changes=e.changes,
            ip_address=e.ip_address,
            created_at=e.created_at.isoformat(),
        )
        for e in result.scalars().all()
    ]
