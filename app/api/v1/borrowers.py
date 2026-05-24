"""Borrower management API endpoints."""
from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.borrower import Borrower
from app.models.database.call import Call
from app.models.database.compliance import ComplianceEvent
from app.models.database.conversation import BehavioralEvent, ConversationTurn, RepaymentPromise
from sqlalchemy import func
from app.models.database.call_analysis import CallAnalysis
from app.models.database.user import User
from app.models.schemas.borrower import BorrowerCreate, BorrowerProfile, BorrowerUpdate, OptOutRequest
from app.models.schemas.call_analysis import BorrowerIntelligenceResponse, CallAnalysisResponse
from app.services.compliance.opt_out_handler import process_opt_out
from app.utils.crypto import encrypt_pii, hash_pii

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=BorrowerProfile, status_code=201)
async def create_borrower(
    payload: BorrowerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a new borrower into the system."""
    org_id = current_user.organization_id

    # Check for duplicate by external_id within org
    result = await db.execute(
        select(Borrower).where(
            Borrower.external_id == payload.external_id,
            Borrower.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Borrower with external ID '{payload.external_id}' already exists")

    # Check for duplicate by phone hash within org
    phone_hash = hash_pii(payload.phone)
    result = await db.execute(
        select(Borrower).where(
            Borrower.phone_hash == phone_hash,
            Borrower.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Borrower with this phone number already exists")

    borrower = Borrower(
        organization_id=org_id,
        external_id=payload.external_id,
        phone_e164=encrypt_pii(payload.phone),
        phone_hash=phone_hash,
        first_name=payload.first_name,
        last_name=payload.last_name,
        time_zone=payload.time_zone,
        preferred_language=payload.preferred_language,
        original_creditor=payload.original_creditor,
        principal_amount=payload.principal_amount,
        current_balance=payload.current_balance,
        interest_rate=payload.interest_rate,
        days_past_due=payload.days_past_due,
        debt_type=payload.debt_type,
        consent_recorded=payload.consent_recorded,
    )
    db.add(borrower)
    await db.flush()
    return borrower


@router.get("", response_model=list[BorrowerProfile])
async def list_borrowers(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all borrowers with pagination."""
    result = await db.execute(
        select(Borrower)
        .where(Borrower.organization_id == current_user.organization_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{borrower_id}", response_model=BorrowerProfile)
async def get_borrower(
    borrower_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return borrower


@router.patch("/{borrower_id}", response_model=BorrowerProfile)
async def update_borrower(
    borrower_id: uuid.UUID,
    payload: BorrowerUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(borrower, field, value)
    return borrower


@router.delete("/{borrower_id}", status_code=204)
async def delete_borrower(
    borrower_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a borrower and all associated records."""
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    # Delete children in FK-safe order
    call_ids = (await db.execute(select(Call.id).where(Call.borrower_id == borrower_id))).scalars().all()
    if call_ids:
        await db.execute(sql_delete(ConversationTurn).where(ConversationTurn.call_id.in_(call_ids)))
    await db.execute(sql_delete(RepaymentPromise).where(RepaymentPromise.borrower_id == borrower_id))
    await db.execute(sql_delete(BehavioralEvent).where(BehavioralEvent.borrower_id == borrower_id))
    await db.execute(sql_delete(ComplianceEvent).where(ComplianceEvent.borrower_id == borrower_id))
    await db.execute(sql_delete(Call).where(Call.borrower_id == borrower_id))
    await db.delete(borrower)
    return None


@router.get("/{borrower_id}/intelligence", response_model=BorrowerIntelligenceResponse)
async def get_borrower_intelligence(
    borrower_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full intelligence history for a borrower — all call analyses + aggregate scores.
    Analyses are ordered newest first.
    """
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")

    analyses_result = await db.execute(
        select(CallAnalysis)
        .where(CallAnalysis.borrower_id == borrower_id)
        .order_by(CallAnalysis.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    analyses = analyses_result.scalars().all()

    # Count calls by type
    counts_result = await db.execute(
        select(Call.call_type, func.count(Call.id).label("cnt"))
        .where(Call.borrower_id == borrower_id)
        .group_by(Call.call_type)
    )
    call_counts = {row.call_type: row.cnt for row in counts_result}

    return BorrowerIntelligenceResponse(
        borrower_id=borrower_id,
        repayment_likelihood=borrower.repayment_likelihood,
        sentiment_trend=borrower.sentiment_trend,
        engagement_score=borrower.engagement_score,
        analyses=analyses,
        total_human_calls=call_counts.get("human_agent", 0),
        total_ai_calls=call_counts.get("ai_agent", 0),
    )


@router.get("/{borrower_id}/behavioral-events")
async def get_behavioral_events(
    borrower_id: uuid.UUID,
    event_type: str | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify borrower belongs to org
    result = await db.execute(
        select(Borrower.id).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Borrower not found")

    q = select(BehavioralEvent).where(BehavioralEvent.borrower_id == borrower_id)
    if event_type:
        q = q.where(BehavioralEvent.event_type == event_type)
    q = q.order_by(BehavioralEvent.detected_at.desc()).limit(limit)
    result = await db.execute(q)
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "call_id": str(e.call_id) if e.call_id else None,
            "event_type": e.event_type,
            "event_data": e.event_data,
            "detected_at": e.detected_at.isoformat(),
        }
        for e in events
    ]


@router.post("/{borrower_id}/opt-out", status_code=200)
async def opt_out_borrower(
    borrower_id: uuid.UUID,
    payload: OptOutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process a cease-and-desist or TCPA opt-out request."""
    result = await db.execute(
        select(Borrower).where(
            Borrower.id == borrower_id,
            Borrower.organization_id == current_user.organization_id,
        )
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")

    await process_opt_out(
        borrower=borrower,
        db=db,
        trigger=payload.reason or "manual_opt_out",
        channel=payload.channel,
    )
    return {"opted_out": True, "timestamp": borrower.opted_out_at}
