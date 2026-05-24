"""
Feature engineering for the ML strategy classifier.
Produces the numeric feature vector fed to XGBoost at inference time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.models.database.borrower import Borrower

DEBT_TYPE_ENCODING: dict[str, int] = {
    "credit_card": 0,
    "medical": 1,
    "auto": 2,
    "student": 3,
    "personal": 4,
    "mortgage": 5,
    "other": 6,
}

FEATURE_NAMES = [
    "days_past_due",
    "log_balance",
    "debt_type_encoded",
    "time_of_day_hour",
    "day_of_week",
    "previous_attempts",
    "avg_sentiment_previous",
    "avoidance_score",
    "engagement_score",
    "promise_kept_rate",
    "hardship_flag",
    "successful_contact_rate",
]


@dataclass
class FeatureVector:
    features: np.ndarray
    feature_names: list[str]


def extract_features(
    borrower: Borrower,
    previous_attempts: int = 0,
    avg_sentiment_previous: float = 0.0,
    hardship_flag: bool = False,
    call_time: Optional[datetime] = None,
) -> FeatureVector:
    """
    Extract the feature vector for a borrower at call time.
    Used for both training data generation and live inference.
    """
    now = call_time or datetime.now(timezone.utc)

    days_past_due = float(borrower.days_past_due or 0)
    log_balance = float(np.log1p(float(borrower.current_balance or 0)))
    debt_type_enc = float(DEBT_TYPE_ENCODING.get(borrower.debt_type or "other", 6))
    hour = float(now.hour)
    dow = float(now.weekday())   # 0=Monday
    prev_attempts = float(previous_attempts)
    avg_sentiment = float(avg_sentiment_previous)
    avoidance = float(borrower.avoidance_score or 0)
    engagement = float(borrower.engagement_score or 0.5)
    promise_kept = float(borrower.promise_kept_rate or 0.5)
    hardship = float(hardship_flag)
    total = float(borrower.total_calls or 1)
    successful = float(borrower.successful_contacts or 0)
    contact_rate = successful / total if total > 0 else 0.0

    features = np.array([
        days_past_due,
        log_balance,
        debt_type_enc,
        hour,
        dow,
        prev_attempts,
        avg_sentiment,
        avoidance,
        engagement,
        promise_kept,
        hardship,
        contact_rate,
    ], dtype=np.float32)

    return FeatureVector(features=features, feature_names=FEATURE_NAMES)
