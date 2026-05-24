"""Call management API endpoints."""
from __future__ import annotations

import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.borrower import Borrower
from app.models.database.call import Call
from app.models.database.conversation import ConversationTurn
from app.models.database.user import User
from app.models.schemas.call import (
    CallDetail, CallInitiate, CallInitiateResponse,
    CallTranscript, CallUpdate, FollowUpBrief, SentimentPoint, TranscriptTurn,
)
from app.models.database.call_analysis import CallAnalysis
from app.models.schemas.call_analysis import CallAnalysisResponse
from app.services.telephony.call_controller import initiate_outbound_call
from app.services.compliance.fdcpa_guard import FDCPAViolationError
from app.services.follow_up.follow_up_brief import build_follow_up_brief

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/initiate", response_model=CallInitiateResponse, status_code=202)
async def initiate_call(
    payload: CallInitiate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an outbound call to a borrower."""
    org_id = current_user.organization_id

    result = await db.execute(
        select(Borrower).where(Borrower.id == payload.borrower_id, Borrower.organization_id == org_id)
    )
    borrower = result.scalar_one_or_none()
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    if not borrower.is_contactable:
        raise HTTPException(status_code=422, detail="Borrower is not contactable (DNC/opt-out/bankruptcy)")
    if payload.follow_up_source_call_id:
        source_call = await db.get(Call, payload.follow_up_source_call_id)
        if not source_call or source_call.organization_id != org_id:
            raise HTTPException(status_code=404, detail="Follow-up source call not found")
        if source_call.borrower_id != borrower.id:
            raise HTTPException(status_code=422, detail="Follow-up source call does not belong to this borrower")

    # Update borrower's preferred language for this call
    if payload.language and payload.language != borrower.preferred_language:
        borrower.preferred_language = payload.language
        await db.commit()  # persist NOW — WebSocket handler reads this from DB

    try:
        call = await initiate_outbound_call(
            borrower=borrower,
            db=db,
            campaign_id=payload.campaign_id,
            strategy_hint=payload.strategy_override,
            follow_up_enabled=payload.follow_up_enabled,
            follow_up_source_call_id=payload.follow_up_source_call_id,
        )
    except FDCPAViolationError as exc:
        raise HTTPException(status_code=422, detail=f"FDCPA compliance check failed: {exc.reason}") from exc
    except Exception as exc:
        logger.error("Call initiation failed for borrower %s: %s", payload.borrower_id, exc)
        raise HTTPException(status_code=503, detail=f"Telephony service unavailable: {exc}") from exc
    return CallInitiateResponse(
        call_id=call.id,
        twilio_call_sid=call.twilio_call_sid,
        status=call.status,
        scheduled_at=payload.scheduled_at,
    )


@router.get("/{call_id}/follow-up-brief", response_model=FollowUpBrief)
async def get_follow_up_brief(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    brief = await build_follow_up_brief(db, str(call.borrower_id), str(call_id))
    if not brief:
        raise HTTPException(status_code=404, detail="Follow-up brief not available yet")
    return brief


@router.get("", response_model=list[CallDetail])
async def list_calls(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call)
        .where(Call.organization_id == current_user.organization_id)
        .order_by(Call.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{call_id}", response_model=CallDetail)
async def get_call(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.call_id == call_id)
        .order_by(ConversationTurn.turn_index)
    )
    turns = result.scalars().all()

    sentiment_trajectory = [
        SentimentPoint(
            turn=t.turn_index,
            score=float(t.sentiment_score),
            label=(
                "cooperative" if float(t.sentiment_score) > 0.4 else
                "positive" if float(t.sentiment_score) > 0.1 else
                "hostile" if float(t.sentiment_score) < -0.6 else
                "negative" if float(t.sentiment_score) < -0.2 else
                "neutral"
            ),
        )
        for t in turns if t.sentiment_score is not None
    ]

    llm_lats = [t.llm_latency_ms for t in turns if t.llm_latency_ms]
    tts_lats = [t.tts_latency_ms for t in turns if t.tts_latency_ms]

    detail = CallDetail.model_validate(call)
    detail.sentiment_trajectory = sentiment_trajectory
    if llm_lats and detail.llm_latency_avg_ms is None:
        detail.llm_latency_avg_ms = sum(llm_lats) // len(llm_lats)
    if tts_lats and detail.tts_latency_avg_ms is None:
        detail.tts_latency_avg_ms = sum(tts_lats) // len(tts_lats)
    return detail


@router.get("/{call_id}/transcript", response_model=CallTranscript)
async def get_transcript(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.call_id == call_id)
        .order_by(ConversationTurn.turn_index)
    )
    turns = result.scalars().all()

    return CallTranscript(
        call_id=call_id,
        turns=[
            TranscriptTurn(
                turn_index=t.turn_index,
                speaker=t.speaker,
                text=t.raw_transcript,
                timestamp_ms=t.speech_start_ms,
                sentiment=float(t.sentiment_score) if t.sentiment_score is not None else None,
                intent=t.intent,
                entities=t.entities or {},
                barge_in=t.barge_in,
            )
            for t in turns
        ],
    )


@router.get("/{call_id}/analysis", response_model=CallAnalysisResponse)
async def get_call_analysis(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the AI intelligence report for a completed AI call."""
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Call not found")
    result = await db.execute(
        select(CallAnalysis).where(CallAnalysis.ai_call_id == call_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not yet available — call may still be in progress")
    return analysis


@router.patch("/{call_id}", response_model=CallDetail)
async def update_call(
    call_id: uuid.UUID,
    payload: CallUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if payload.outcome:
        call.outcome = payload.outcome
    return call


@router.delete("/{call_id}", status_code=204)
async def cancel_call(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.organization_id == current_user.organization_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.status not in ("initiated", "pending", "ringing"):
        raise HTTPException(status_code=422, detail="Can only cancel pending/initiated/ringing calls")
    call.status = "canceled"
