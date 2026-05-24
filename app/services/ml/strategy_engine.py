"""
ML-powered strategy selection engine.

Predicts the best collection strategy for a borrower using an XGBoost classifier
trained on historical call outcomes. Falls back to rule-based selection when:
- The model is not yet trained (cold start)
- Model confidence is below threshold
- Compliance overrides require a specific action

Strategies: reminder | negotiation | settlement | escalation | skip
"""
from __future__ import annotations

import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import get_settings
from app.models.database.borrower import Borrower
from app.services.ml.feature_extractor import extract_features

logger = logging.getLogger(__name__)

STRATEGY_LABELS = ["reminder", "negotiation", "settlement", "escalation", "skip"]
MIN_CONFIDENCE = 0.45   # Fall back to rule-based if model is uncertain


@dataclass
class StrategyDecision:
    strategy: str
    confidence: float
    source: str          # "ml" | "rule_based" | "compliance_override"
    settlement_authorized: bool = False
    reason: str = ""


class StrategyEngine:
    """
    Singleton strategy engine with in-memory model caching.
    Model is reloaded from disk every settings.ml_model_refresh_interval_seconds.
    """

    _instance: Optional["StrategyEngine"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "StrategyEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        settings = get_settings()
        self._model_path = Path(settings.ml_models_path) / settings.ml_strategy_model_file
        self._refresh_interval = settings.ml_model_refresh_interval_seconds
        self._model = None
        self._last_loaded: float = 0.0
        self._initialized = True
        self._try_load_model()

    def _try_load_model(self) -> None:
        if self._model_path.exists():
            try:
                with open(self._model_path, "rb") as f:
                    self._model = pickle.load(f)
                self._last_loaded = time.monotonic()
                logger.info("Strategy model loaded from %s", self._model_path)
            except Exception as exc:
                logger.warning("Could not load strategy model: %s", exc)
                self._model = None
        else:
            logger.info("No strategy model found — using rule-based fallback")

    def _maybe_refresh(self) -> None:
        if time.monotonic() - self._last_loaded > self._refresh_interval:
            self._try_load_model()

    def select_strategy(self, borrower: Borrower) -> StrategyDecision:
        """
        Select the best strategy for a borrower.
        Compliance overrides always take precedence over ML predictions.
        """
        # ── Compliance overrides (always checked first) ───────────────────────
        if borrower.opted_out or borrower.do_not_call:
            return StrategyDecision(strategy="skip", confidence=1.0, source="compliance_override", reason="opted_out_or_dnc")
        if borrower.bankruptcy_filed:
            return StrategyDecision(strategy="skip", confidence=1.0, source="compliance_override", reason="bankruptcy_stay")

        # ── ML prediction ─────────────────────────────────────────────────────
        self._maybe_refresh()
        if self._model is not None:
            try:
                fv = extract_features(borrower)
                proba = self._model.predict_proba([fv.features])[0]
                best_idx = int(np.argmax(proba))
                best_strategy = STRATEGY_LABELS[best_idx]
                confidence = float(proba[best_idx])

                if confidence >= MIN_CONFIDENCE and best_strategy != "skip":
                    return StrategyDecision(
                        strategy=best_strategy,
                        confidence=confidence,
                        source="ml",
                        settlement_authorized=(best_strategy == "settlement"),
                    )
            except Exception as exc:
                logger.warning("ML strategy prediction failed: %s", exc)

        # ── Rule-based fallback ───────────────────────────────────────────────
        return self._rule_based(borrower)

    def _rule_based(self, borrower: Borrower) -> StrategyDecision:
        """Simple DPD + behavioral heuristics."""
        dpd = borrower.days_past_due or 0
        avoidance = float(borrower.avoidance_score or 0)
        engagement = float(borrower.engagement_score or 0.5)

        if avoidance > 0.75 and borrower.total_calls > 4:
            strategy = "escalation"
        elif dpd >= 90 and engagement < 0.4:
            strategy = "settlement"
        elif dpd >= 30:
            strategy = "negotiation"
        else:
            strategy = "reminder"

        return StrategyDecision(
            strategy=strategy,
            confidence=0.6,
            source="rule_based",
            settlement_authorized=(strategy == "settlement"),
        )


def get_strategy_engine() -> StrategyEngine:
    return StrategyEngine()
