"""Analytics and reporting API endpoints."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.call import Call
from app.models.database.user import User
from app.models.schemas.analytics import (
    CallQualityResponse, DashboardResponse, DashboardSummary,
    HourlyBreakdown, OutcomeDistribution,
)

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    campaign_id: Optional[uuid.UUID] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate KPIs for the dashboard."""
    query = select(Call).where(Call.organization_id == current_user.organization_id)
    if from_date:
        query = query.where(Call.started_at >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query = query.where(Call.started_at <= datetime.combine(to_date, datetime.max.time()))
    if campaign_id:
        query = query.where(Call.campaign_id == campaign_id)

    result = await db.execute(query)
    calls = result.scalars().all()

    total = len(calls)
    connected = sum(1 for c in calls if c.outcome not in (None, "no_answer", "busy", "voicemail"))
    promises = sum(1 for c in calls if c.outcome == "promise_made")
    avg_duration = sum(c.duration_seconds or 0 for c in calls) / max(total, 1)
    payments = sum(float(c.payment_collected or 0) for c in calls)
    violations = sum(len(c.fdcpa_violations or []) for c in calls)

    summary = DashboardSummary(
        total_calls=total,
        connected_rate=round(connected / max(total, 1), 3),
        promise_rate=round(promises / max(total, 1), 3),
        avg_call_duration=round(avg_duration, 1),
        payment_collected=Decimal(str(round(payments, 2))),
        compliance_violations=violations,
    )

    # Hourly breakdown
    hourly: dict = defaultdict(lambda: {"calls": 0, "connected": 0, "promise_made": 0})
    for c in calls:
        if c.started_at:
            h = c.started_at.hour
            hourly[h]["calls"] += 1
            if c.outcome not in (None, "no_answer", "busy", "voicemail", "failed"):
                hourly[h]["connected"] += 1
            if c.outcome == "promise_made":
                hourly[h]["promise_made"] += 1
    hourly_breakdown = [
        HourlyBreakdown(hour=h, calls=v["calls"], connected=v["connected"], promise_made=v["promise_made"])
        for h, v in sorted(hourly.items())
    ]

    # Outcome distribution
    counts = Counter(c.outcome for c in calls if c.outcome)
    total_with_outcome = sum(counts.values())
    outcome_distribution = [
        OutcomeDistribution(outcome=k, count=v, percentage=round(v / max(total_with_outcome, 1), 3))
        for k, v in counts.most_common()
    ]

    return DashboardResponse(summary=summary, hourly_breakdown=hourly_breakdown, outcome_distribution=outcome_distribution)


@router.get("/call-quality", response_model=CallQualityResponse)
async def get_call_quality(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate latency and quality metrics across all recent calls."""
    result = await db.execute(
        select(
            func.avg(Call.stt_latency_avg_ms).label("stt"),
            func.avg(Call.llm_latency_avg_ms).label("llm"),
            func.avg(Call.tts_latency_avg_ms).label("tts"),
            func.avg(Call.stt_confidence_avg).label("stt_conf"),
            func.sum(Call.interruption_count).label("interruptions"),
            func.sum(Call.turn_count).label("total_turns"),
        ).where(Call.organization_id == current_user.organization_id)
    )
    row = result.one()

    barge_in_rate = round((row.interruptions or 0) / max(row.total_turns or 1, 1), 3)
    stt = float(row.stt) if row.stt else None
    llm = float(row.llm) if row.llm else None
    tts = float(row.tts) if row.tts else None
    e2e = round(llm + tts, 1) if (llm and tts) else None

    # p95 latencies via PostgreSQL percentile_cont
    p95_llm: Optional[float] = None
    p95_tts: Optional[float] = None
    try:
        p95_result = await db.execute(
            select(
                func.percentile_cont(0.95).within_group(Call.llm_latency_avg_ms.asc()).label("p95_llm"),
                func.percentile_cont(0.95).within_group(Call.tts_latency_avg_ms.asc()).label("p95_tts"),
            ).where(
                Call.llm_latency_avg_ms.isnot(None),
                Call.organization_id == current_user.organization_id,
            )
        )
        p95_row = p95_result.one()
        p95_llm = float(p95_row.p95_llm) if p95_row.p95_llm else None
        p95_tts = float(p95_row.p95_tts) if p95_row.p95_tts else None
    except Exception:
        pass

    return CallQualityResponse(
        avg_stt_latency_ms=stt,
        avg_llm_latency_ms=llm,
        avg_tts_latency_ms=tts,
        avg_e2e_latency_ms=e2e,
        barge_in_rate=barge_in_rate,
        stt_confidence_avg=float(row.stt_conf) if row.stt_conf else None,
        p95_stt_latency_ms=None,
        p95_llm_latency_ms=p95_llm,
        p95_tts_latency_ms=p95_tts,
    )
