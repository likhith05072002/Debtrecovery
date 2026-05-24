from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class HumanCallInitiateRequest(BaseModel):
    contact_name: str
    contact_phone: str
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    amount_due: Optional[Decimal] = None
    days_overdue: Optional[int] = None


class HumanCallInitiateResponse(BaseModel):
    call_id: uuid.UUID
    twilio_call_sid: Optional[str] = None
    status: str
    contact_name: Optional[str] = None
    borrower_id: Optional[uuid.UUID] = None


class HumanCallResponse(BaseModel):
    id: uuid.UUID
    borrower_id: Optional[uuid.UUID] = None
    human_agent_id: Optional[str] = None
    human_agent_name: Optional[str] = None
    twilio_call_sid: Optional[str] = None
    status: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    amount_due: Optional[Decimal] = None
    days_overdue: Optional[int] = None
    duration_seconds: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallAnalysisResponse(BaseModel):
    id: uuid.UUID
    human_call_id: Optional[uuid.UUID] = None
    ai_call_id: Optional[uuid.UUID] = None
    borrower_id: Optional[uuid.UUID] = None
    transcription_status: str
    analysis_status: str
    transcript_text: Optional[str] = None
    transcript_speakers: list[dict] = []
    overall_sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    willingness_to_pay: Optional[str] = None
    payment_intent_score: Optional[float] = None
    key_points: list[str] = []
    borrower_characterization: Optional[str] = None
    repayment_probability: Optional[float] = None
    repayment_probability_reason: Optional[str] = None
    recommended_strategy: Optional[str] = None
    next_call_talking_points: list[str] = []
    analysis_model: Optional[str] = None
    analysis_error: Optional[str] = None
    analysis_completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BorrowerIntelligenceResponse(BaseModel):
    borrower_id: uuid.UUID
    repayment_likelihood: Decimal
    sentiment_trend: str
    engagement_score: Decimal
    analyses: list[CallAnalysisResponse]
    total_human_calls: int
    total_ai_calls: int
