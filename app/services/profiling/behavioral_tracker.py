"""
Behavioral signal tracking and exponential decay scoring.

For each behavioral event, a weighted score contribution is calculated
with an exponential decay over time. This produces engagement_score and
avoidance_score for each borrower — core inputs to the ML strategy engine.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.conversation import BehavioralEvent

logger = logging.getLogger(__name__)


@dataclass
class SignalConfig:
    weight: float
    decay_days: float
    category: str   # "engagement" | "avoidance" | "hostility"


# Signal registry with weights and decay periods
BEHAVIORAL_SIGNALS: dict[str, SignalConfig] = {
    # Engagement signals
    "call_answered":          SignalConfig(weight=0.10, decay_days=30,  category="engagement"),
    "full_conversation":      SignalConfig(weight=0.15, decay_days=60,  category="engagement"),
    "callback_accepted":      SignalConfig(weight=0.20, decay_days=45,  category="engagement"),
    "promise_made":           SignalConfig(weight=0.25, decay_days=90,  category="engagement"),
    "promise_kept":           SignalConfig(weight=0.35, decay_days=180, category="engagement"),
    "payment_made":           SignalConfig(weight=0.40, decay_days=365, category="engagement"),
    "voluntary_contact":      SignalConfig(weight=0.30, decay_days=90,  category="engagement"),
    # Avoidance signals
    "no_answer":              SignalConfig(weight=0.05, decay_days=14,  category="avoidance"),
    "hung_up_early":          SignalConfig(weight=0.12, decay_days=21,  category="avoidance"),
    "voicemail_only":         SignalConfig(weight=0.08, decay_days=14,  category="avoidance"),
    "promise_broken":         SignalConfig(weight=0.20, decay_days=60,  category="avoidance"),
    "callback_not_honored":   SignalConfig(weight=0.18, decay_days=45,  category="avoidance"),
    # Hostility signals
    "abusive_language":       SignalConfig(weight=0.30, decay_days=90,   category="hostility"),
    "legal_threat_made":      SignalConfig(weight=1.00, decay_days=9999, category="hostility"),
    "cease_desist_requested": SignalConfig(weight=1.00, decay_days=9999, category="hostility"),
    "dispute_raised":         SignalConfig(weight=0.50, decay_days=365,  category="hostility"),
}


def _decayed_weight(weight: float, decay_days: float, days_since: float) -> float:
    """Compute exponentially decayed weight contribution."""
    return weight * math.exp(-days_since / decay_days)


def compute_scores(events: list[BehavioralEvent]) -> tuple[float, float]:
    """
    Compute (engagement_score, avoidance_score) from a list of behavioral events.
    Both scores are normalized to [0.0, 1.0].
    """
    now = datetime.now(timezone.utc)
    engagement_sum = 0.0
    avoidance_sum = 0.0

    for event in events:
        config = BEHAVIORAL_SIGNALS.get(event.event_type)
        if not config:
            continue

        days_since = (now - event.detected_at).total_seconds() / 86400
        contribution = _decayed_weight(config.weight, config.decay_days, days_since)

        if config.category == "engagement":
            engagement_sum += contribution
        elif config.category in ("avoidance", "hostility"):
            avoidance_sum += contribution

    # Normalize using sigmoid-like clamping
    engagement_score = min(1.0, engagement_sum)
    avoidance_score = min(1.0, avoidance_sum)

    return round(engagement_score, 3), round(avoidance_score, 3)


async def log_behavioral_event(
    borrower_id: str,
    event_type: str,
    db: AsyncSession,
    call_id: Optional[str] = None,
    event_data: Optional[dict] = None,
    confidence: float = 1.0,
) -> BehavioralEvent:
    """Persist a behavioral signal event to the database."""
    event = BehavioralEvent(
        borrower_id=borrower_id,
        call_id=call_id,
        event_type=event_type,
        event_data=event_data or {},
        confidence=confidence,
    )
    db.add(event)
    logger.debug("Behavioral event logged: borrower=%s type=%s", borrower_id, event_type)
    return event
