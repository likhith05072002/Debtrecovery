"""
Aggregate borrower profile scoring — updates the denormalized score columns
on the borrowers table after each call. Called asynchronously via Celery.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.borrower import Borrower
from app.models.database.call import Call
from app.models.database.conversation import BehavioralEvent, RepaymentPromise
from app.services.profiling.behavioral_tracker import compute_scores
from app.services.profiling.sentiment_analyzer import analyze_sentiment

logger = logging.getLogger(__name__)


async def update_borrower_scores(borrower_id: str, db: AsyncSession) -> None:
    """
    Recompute and persist all behavioral scores for a borrower.
    Called after every call completes.
    """
    borrower = await db.get(Borrower, borrower_id)
    if not borrower:
        logger.warning("Borrower %s not found for score update", borrower_id)
        return

    # Fetch all behavioral events
    result = await db.execute(
        select(BehavioralEvent)
        .where(BehavioralEvent.borrower_id == borrower.id)
        .order_by(BehavioralEvent.detected_at.desc())
    )
    events = result.scalars().all()

    # Compute engagement + avoidance scores
    engagement_score, avoidance_score = compute_scores(list(events))
    borrower.engagement_score = engagement_score
    borrower.avoidance_score = avoidance_score

    # Compute promise_kept_rate
    promises_result = await db.execute(
        select(RepaymentPromise).where(RepaymentPromise.borrower_id == borrower.id)
    )
    promises = promises_result.scalars().all()
    if promises:
        kept = sum(1 for p in promises if p.status == "kept")
        borrower.promise_kept_rate = round(kept / len(promises), 3)

    # Compute sentiment trend from recent calls (last 5)
    calls_result = await db.execute(
        select(Call)
        .where(Call.borrower_id == borrower.id, Call.final_sentiment.isnot(None))
        .order_by(Call.started_at.desc())
        .limit(5)
    )
    recent_calls = calls_result.scalars().all()
    if recent_calls:
        # EWMA of final sentiment labels → score
        sentiment_map = {"cooperative": 0.8, "positive": 0.5, "neutral": 0.0, "negative": -0.4, "hostile": -0.8}
        scores = [sentiment_map.get(c.final_sentiment, 0.0) for c in recent_calls]
        # Exponentially weighted mean (most recent has highest weight)
        alpha = 0.4
        ewma = scores[0]
        for s in scores[1:]:
            ewma = alpha * s + (1 - alpha) * ewma
        if ewma > 0.3:
            borrower.sentiment_trend = "positive"
        elif ewma > -0.3:
            borrower.sentiment_trend = "neutral"
        elif ewma > -0.7:
            borrower.sentiment_trend = "negative"
        else:
            borrower.sentiment_trend = "hostile"

    logger.info(
        "Scores updated for borrower %s: engagement=%.3f avoidance=%.3f sentiment=%s",
        borrower_id, engagement_score, avoidance_score, borrower.sentiment_trend
    )
