from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CallInitiate(BaseModel):
    borrower_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    strategy_override: Optional[str] = Field(default=None, pattern="^(reminder|negotiation|settlement|escalation)$")
    scheduled_at: Optional[datetime] = None
    language: Optional[str] = "en"  # "en" | "hi" | "kn" | "te"
    follow_up_enabled: bool = False
    follow_up_source_call_id: Optional[uuid.UUID] = None


class CallInitiateResponse(BaseModel):
    call_id: uuid.UUID
    twilio_call_sid: Optional[str]
    status: str
    scheduled_at: Optional[datetime]


class SentimentPoint(BaseModel):
    turn: int
    score: float
    label: str


class PromiseInfo(BaseModel):
    amount: Optional[Decimal]
    date: Optional[date]
    status: str


class CallDetail(BaseModel):
    id: uuid.UUID
    twilio_call_sid: Optional[str]
    borrower_id: uuid.UUID
    campaign_id: Optional[uuid.UUID]
    status: str
    outcome: Optional[str]
    duration_seconds: Optional[int]
    turn_count: int
    interruption_count: int
    llm_latency_avg_ms: Optional[int]
    tts_latency_avg_ms: Optional[int]
    stt_latency_avg_ms: Optional[int]
    sentiment_trajectory: list[SentimentPoint] = []
    compliance_passed: bool
    fdcpa_violations: list = []
    promise: Optional[PromiseInfo] = None
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CallUpdate(BaseModel):
    outcome: Optional[str] = None
    notes: Optional[str] = None


class TranscriptTurn(BaseModel):
    turn_index: int
    speaker: str
    text: Optional[str]
    timestamp_ms: Optional[int]
    sentiment: Optional[float]
    intent: Optional[str]
    entities: dict = {}
    barge_in: bool = False

    model_config = {"from_attributes": True}


class CallTranscript(BaseModel):
    call_id: uuid.UUID
    turns: list[TranscriptTurn]


class FollowUpBrief(BaseModel):
    borrower_id: uuid.UUID
    source_call_id: uuid.UUID
    source_call_created_at: datetime
    analysis_status: str
    title: str
    summary: str
    key_points: list[str] = []
    next_call_focus: list[str] = []
    suggested_opening: str
    transcript_snippets: list[str] = []
