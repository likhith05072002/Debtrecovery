"""
Smart call scheduler — determines when to retry a call based on the
previous outcome, borrower behavior patterns, and FDCPA frequency caps.

Retry rules are data-driven and incorporate time-of-day optimization.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database.borrower import Borrower
from app.models.database.campaign import CallSchedule, CampaignBorrower

logger = logging.getLogger(__name__)

# ── Retry rules keyed by last call outcome ────────────────────────────────────

RETRY_RULES: dict[str, dict] = {
    "no_answer": {
        "max_attempts": 6,
        "intervals_hrs": [2, 4, 8, 24, 48, 72],
        "time_shift": True,
    },
    "busy": {
        "max_attempts": 3,
        "intervals_hrs": [0.5, 1.0, 2.0],
        "time_shift": False,
    },
    "voicemail": {
        "max_attempts": 3,
        "intervals_hrs": [24, 48, 72],
        "leave_voicemail": True,
    },
    "hung_up_early": {
        "max_attempts": 4,
        "intervals_hrs": [4, 24, 48, 96],
        "strategy_escalate": True,
    },
    "refused": {
        "max_attempts": 2,
        "intervals_hrs": [72, 168],
        "strategy": "settlement",
    },
    "connected_no_outcome": {
        "max_attempts": 4,
        "intervals_hrs": [24, 48, 72, 168],
    },
    "promise_made": {
        "follow_up": True,
        "follow_up_days": 1,   # 1 day after promised date
        "strategy": "payment_confirmation",
    },
}

# Default call windows (local borrower time)
DEFAULT_CALL_HOURS = [10, 11, 14, 15, 17, 18]
JITTER_MINUTES = 30


async def schedule_next_call(
    borrower: Borrower,
    db: AsyncSession,
    last_outcome: str,
    attempt_number: int,
    campaign_id: Optional[str] = None,
    promise_date: Optional[datetime] = None,
) -> Optional[CallSchedule]:
    """
    Determine and persist the next call attempt for this borrower.
    Returns None if no retry should be made.
    """
    settings = get_settings()
    rule = RETRY_RULES.get(last_outcome, RETRY_RULES["connected_no_outcome"])

    # Check max attempts
    max_attempts = rule.get("max_attempts", 5)
    if attempt_number > max_attempts:
        logger.info("Max attempts (%d) reached for borrower %s", max_attempts, borrower.id)
        return None

    # Determine base interval
    intervals = rule.get("intervals_hrs", [24])
    interval_idx = min(attempt_number - 1, len(intervals) - 1)
    interval_hrs = intervals[interval_idx]

    # Handle promise follow-up
    if rule.get("follow_up") and promise_date:
        target_dt = promise_date + timedelta(days=rule.get("follow_up_days", 1))
    else:
        target_dt = datetime.now(timezone.utc) + timedelta(hours=interval_hrs)

    # Align to call window (8 AM – 9 PM local time)
    target_dt = _align_to_call_window(target_dt, borrower.time_zone, rule.get("time_shift", False), attempt_number)

    # Add jitter to prevent thundering herd
    jitter = random.randint(-JITTER_MINUTES, JITTER_MINUTES)
    target_dt += timedelta(minutes=jitter)

    # Strategy hint for next attempt
    strategy_hint = rule.get("strategy")
    if rule.get("strategy_escalate") and attempt_number >= 2:
        strategy_hint = "escalation"

    schedule = CallSchedule(
        borrower_id=borrower.id,
        campaign_id=campaign_id,
        scheduled_at=target_dt,
        priority=_priority_from_outcome(last_outcome),
        attempt_number=attempt_number,
        strategy_hint=strategy_hint,
        status="pending",
    )
    db.add(schedule)
    logger.info(
        "Next call scheduled for borrower %s at %s (attempt %d, strategy=%s)",
        borrower.id, target_dt.isoformat(), attempt_number, strategy_hint
    )
    return schedule


def _align_to_call_window(
    target: datetime,
    time_zone: str,
    time_shift: bool,
    attempt_number: int,
) -> datetime:
    """
    Ensure target datetime falls within the FDCPA call window (8 AM – 9 PM local).
    If time_shift=True, vary the hour across attempts to reach borrowers at different times.
    """
    settings = get_settings()
    try:
        tz = pytz.timezone(time_zone)
    except Exception:
        tz = pytz.UTC

    local_target = target.astimezone(tz)
    hour = local_target.hour

    if time_shift:
        # Rotate through preferred call hours based on attempt number
        preferred_hour = DEFAULT_CALL_HOURS[attempt_number % len(DEFAULT_CALL_HOURS)]
    else:
        preferred_hour = hour if settings.fdcpa_call_window_start <= hour < settings.fdcpa_call_window_end else DEFAULT_CALL_HOURS[0]

    # If current hour is outside window, advance to next day at preferred hour
    if not (settings.fdcpa_call_window_start <= local_target.hour < settings.fdcpa_call_window_end):
        local_target = local_target.replace(hour=preferred_hour, minute=0, second=0, microsecond=0)
        if local_target <= datetime.now(tz):
            local_target += timedelta(days=1)
    else:
        local_target = local_target.replace(hour=preferred_hour, minute=0, second=0, microsecond=0)

    return local_target.astimezone(timezone.utc)


def _priority_from_outcome(outcome: str) -> int:
    """Higher priority (lower number) for more engaged borrowers."""
    priority_map = {
        "promise_made": 1,
        "callback_requested": 2,
        "connected_no_outcome": 3,
        "hung_up_early": 4,
        "voicemail": 6,
        "no_answer": 7,
        "refused": 8,
    }
    return priority_map.get(outcome, 5)
