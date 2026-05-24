"""
Post-call ML feature extraction and outcome storage.
Feeds the ml_call_outcomes table which is the training data source for model retraining.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.borrower import Borrower
from app.models.database.call import Call
from app.models.database.ml_outcome import MLCallOutcome
from app.models.database.conversation import BehavioralEvent
from app.services.ml.feature_extractor import extract_features

logger = logging.getLogger(__name__)


async def record_call_outcome(
    call: Call,
    borrower: Borrower,
    db: AsyncSession,
    model_version: str = "v0",
) -> None:
    """
    Extract features and persist a training record for this call.
    Called by the post_call_analysis Celery task after every call.
    """
    # Previous call outcomes
    prev_calls_result = await db.execute(
        select(Call)
        .where(Call.borrower_id == borrower.id, Call.id != call.id)
        .order_by(Call.started_at.desc())
        .limit(10)
    )
    prev_calls = prev_calls_result.scalars().all()
    previous_outcomes = [c.outcome for c in prev_calls if c.outcome]
    previous_attempts = len(prev_calls)

    # Average sentiment from previous calls
    sentiments = []
    sentiment_map = {"cooperative": 0.8, "positive": 0.5, "neutral": 0.0, "negative": -0.4, "hostile": -0.8}
    for c in prev_calls:
        if c.final_sentiment:
            sentiments.append(sentiment_map.get(c.final_sentiment, 0.0))
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

    # Check if hardship was signaled in this call
    events_result = await db.execute(
        select(BehavioralEvent)
        .where(BehavioralEvent.call_id == call.id, BehavioralEvent.event_type == "hardship_expressed")
    )
    hardship_flag = events_result.first() is not None

    feature_vector = extract_features(
        borrower,
        previous_attempts=previous_attempts,
        avg_sentiment_previous=avg_sentiment,
        hardship_flag=hardship_flag,
        call_time=call.started_at,
    )

    outcome = MLCallOutcome(
        call_id=call.id,
        borrower_id=borrower.id,
        days_past_due=borrower.days_past_due,
        balance=borrower.current_balance,
        debt_type=borrower.debt_type,
        time_of_day_hour=call.started_at.hour if call.started_at else None,
        day_of_week=call.started_at.weekday() if call.started_at else None,
        previous_attempts=previous_attempts,
        previous_outcomes=previous_outcomes[:5],
        avg_sentiment_previous=avg_sentiment,
        avoidance_score=float(borrower.avoidance_score or 0),
        engagement_score=float(borrower.engagement_score or 0.5),
        strategy_used=None,   # Populated by session orchestrator
        outcome_label=call.outcome,
        model_version=model_version,
    )
    db.add(outcome)
    logger.debug("ML outcome recorded for call %s: outcome=%s", call.id, call.outcome)
