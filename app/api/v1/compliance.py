"""Compliance management endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.borrower import Borrower
from app.models.database.compliance import ComplianceEvent
from app.models.database.user import User
from app.services.compliance.consent_manager import record_consent

router = APIRouter()


class ComplianceEventOut(BaseModel):
    id: str
    borrower_id: str
    call_id: Optional[str]
    event_type: str
    severity: str
    description: Optional[str]
    auto_actioned: bool
    created_at: str


def _serialize_event(e: ComplianceEvent) -> ComplianceEventOut:
    return ComplianceEventOut(
        id=str(e.id),
        borrower_id=str(e.borrower_id),
        call_id=str(e.call_id) if e.call_id else None,
        event_type=e.event_type,
        severity=e.severity,
        description=e.description,
        auto_actioned=e.auto_actioned,
        created_at=e.created_at.isoformat(),
    )


@router.post("/consent/{borrower_id}", status_code=201)
async def record_borrower_consent(
    borrower_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record TCPA consent for a borrower (required before automated calls)."""
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    await record_consent(borrower, db)
    return {"consent_recorded": True, "borrower_id": str(borrower_id)}


@router.get("/events", response_model=list[ComplianceEventOut])
async def list_recent_compliance_events(
    limit: int = Query(default=50, le=200),
    severity: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent compliance events across all borrowers, newest first."""
    query = (
        select(ComplianceEvent)
        .where(ComplianceEvent.organization_id == current_user.organization_id)
        .order_by(ComplianceEvent.created_at.desc())
        .limit(limit)
    )
    if severity:
        query = query.where(ComplianceEvent.severity == severity)
    result = await db.execute(query)
    return [_serialize_event(e) for e in result.scalars().all()]


@router.get("/events/{borrower_id}", response_model=list[ComplianceEventOut])
async def get_compliance_events(
    borrower_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all compliance events for a borrower (audit trail), newest first."""
    # Verify borrower belongs to org
    result = await db.execute(
        select(Borrower.id).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Borrower not found")

    result = await db.execute(
        select(ComplianceEvent)
        .where(ComplianceEvent.borrower_id == borrower_id)
        .order_by(ComplianceEvent.created_at.desc())
        .limit(100)
    )
    return [_serialize_event(e) for e in result.scalars().all()]
