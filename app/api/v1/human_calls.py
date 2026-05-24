"""Human agent call management API — completely independent from AI agent calls."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_current_user, get_db
from app.models.database.human_call import HumanCall
from app.models.database.call_analysis import CallAnalysis
from app.models.database.user import User
from app.models.schemas.call_analysis import (
    CallAnalysisResponse,
    HumanCallInitiateRequest,
    HumanCallInitiateResponse,
    HumanCallResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/token")
async def get_twilio_token(
    agent_id: str = "agent",
    current_user: User = Depends(get_current_user),
):
    """
    Generate a Twilio Access Token for the browser-based Twilio Client SDK.
    The frontend uses this token to open a Device and make outbound calls
    directly from the browser (WebRTC / microphone).
    """
    settings = get_settings()

    if not settings.twilio_api_key_sid or not settings.twilio_twiml_app_sid:
        raise HTTPException(
            status_code=503,
            detail="Twilio Client SDK not configured. Set TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_TWIML_APP_SID in .env",
        )

    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant

    token = AccessToken(
        settings.twilio_account_sid,
        settings.twilio_api_key_sid,
        settings.twilio_api_key_secret,
        identity=agent_id,
        ttl=3600,   # 1 hour
    )
    voice_grant = VoiceGrant(
        outgoing_application_sid=settings.twilio_twiml_app_sid,
        incoming_allow=False,   # human agents only make outbound calls
    )
    token.add_grant(voice_grant)

    return {"token": token.to_jwt(), "identity": agent_id}


@router.get("", response_model=list[HumanCallResponse])
async def list_human_calls(
    skip: int = 0,
    limit: int = 100,
    borrower_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all human-agent calls, newest first. Filter by borrower_id if provided."""
    query = (
        select(HumanCall)
        .where(HumanCall.organization_id == current_user.organization_id)
        .order_by(HumanCall.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if borrower_id:
        query = query.where(HumanCall.borrower_id == borrower_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/initiate", response_model=HumanCallInitiateResponse, status_code=202)
async def initiate_human_call(
    payload: HumanCallInitiateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a HumanCall record. The actual Twilio call is initiated by the
    browser via the Twilio Client SDK (device.connect). Twilio then hits
    /telephony/voice_client which looks up this record to get the borrower's phone.
    """
    settings = get_settings()

    human_call = HumanCall(
        organization_id=current_user.organization_id,
        borrower_id=None,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        amount_due=payload.amount_due,
        days_overdue=payload.days_overdue,
        human_agent_id=payload.agent_id,
        human_agent_name=payload.agent_name,
        from_number=settings.twilio_from_number,
        to_number=payload.contact_phone,
        status="initiated",
        started_at=datetime.now(timezone.utc),
    )
    db.add(human_call)
    await db.flush()
    await db.commit()

    logger.info("Human call record created: id=%s contact=%s agent=%s", human_call.id, payload.contact_name, payload.agent_name)

    return HumanCallInitiateResponse(
        call_id=human_call.id,
        twilio_call_sid=None,
        status=human_call.status,
        contact_name=human_call.contact_name,
    )


@router.get("/{call_id}", response_model=HumanCallResponse)
async def get_human_call(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single human call record."""
    result = await db.execute(
        select(HumanCall).where(
            HumanCall.id == call_id,
            HumanCall.organization_id == current_user.organization_id,
        )
    )
    human_call = result.scalar_one_or_none()
    if not human_call:
        raise HTTPException(status_code=404, detail="Human call not found")
    return human_call


@router.get("/{call_id}/analysis", response_model=CallAnalysisResponse)
async def get_call_analysis(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the AI intelligence report for a completed human-agent call.
    Returns 404 if the analysis hasn't started yet.
    """
    result = await db.execute(
        select(HumanCall).where(
            HumanCall.id == call_id,
            HumanCall.organization_id == current_user.organization_id,
        )
    )
    human_call = result.scalar_one_or_none()
    if not human_call:
        raise HTTPException(status_code=404, detail="Human call not found")

    result = await db.execute(
        select(CallAnalysis).where(CallAnalysis.human_call_id == call_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="Analysis not yet available — call may still be in progress",
        )
    return analysis
