from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_calls: int
    connected_rate: float
    promise_rate: float
    avg_call_duration: float
    payment_collected: Decimal
    compliance_violations: int


class HourlyBreakdown(BaseModel):
    hour: int
    calls: int
    connected: int
    promise_made: int


class OutcomeDistribution(BaseModel):
    outcome: str
    count: int
    percentage: float


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    hourly_breakdown: list[HourlyBreakdown]
    outcome_distribution: list[OutcomeDistribution]


class CallQualityResponse(BaseModel):
    avg_stt_latency_ms: Optional[float]
    avg_llm_latency_ms: Optional[float]
    avg_tts_latency_ms: Optional[float]
    avg_e2e_latency_ms: Optional[float]
    barge_in_rate: float
    stt_confidence_avg: Optional[float]
    p95_stt_latency_ms: Optional[float]
    p95_llm_latency_ms: Optional[float]
    p95_tts_latency_ms: Optional[float]
