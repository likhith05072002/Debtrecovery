"""
Standalone script to train the XGBoost strategy classifier.

Usage:
    python ml/training/train_strategy_model.py [--min-rows 100]

Reads from the ml_call_outcomes table, trains the model, and saves to ml/models/.
This is equivalent to what the Celery ml_tasks.retrain_strategy_model task does,
but can be run manually during development or bootstrap.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pickle
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LABEL_MAP = {
    "promise_made": 0,
    "payment_arranged": 1,
    "refused": 2,
    "voicemail": 3,
    "no_answer": 3,
    "dispute_filed": 4,
    "escalated": 4,
}

LABEL_NAMES = ["promise_made", "payment_arranged", "refused", "voicemail_no_answer", "dispute_escalated"]


async def load_training_data():
    from app.models.database.base import AsyncSessionLocal
    from app.models.database.ml_outcome import MLCallOutcome
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MLCallOutcome).where(MLCallOutcome.outcome_label.isnot(None))
        )
        rows = result.scalars().all()

    X, y = [], []
    from app.services.ml.feature_extractor import DEBT_TYPE_ENCODING
    for row in rows:
        label = LABEL_MAP.get(row.outcome_label or "", -1)
        if label < 0:
            continue
        features = [
            float(row.days_past_due or 0),
            float(np.log1p(float(row.balance or 0))),
            float(DEBT_TYPE_ENCODING.get(row.debt_type or "other", 6)),
            float(row.time_of_day_hour or 12),
            float(row.day_of_week or 0),
            float(row.previous_attempts or 0),
            float(row.avg_sentiment_previous or 0),
            float(row.avoidance_score or 0),
            float(row.engagement_score or 0.5),
            0.5, 0.0, 0.5,  # placeholder features
        ]
        X.append(features)
        y.append(label)

    return np.array(X, dtype=np.float32), np.array(y)


def train(X: np.ndarray, y: np.ndarray, model_output: Path) -> float:
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import label_binarize

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        use_label_encoder=False,
        eval_metric="mlogloss",
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=True,
        early_stopping_rounds=20,
    )

    proba = model.predict_proba(X_val)
    classes = sorted(set(y))
    y_bin = label_binarize(y_val, classes=classes)
    auc = roc_auc_score(y_bin, proba[:, :len(classes)], multi_class="ovr", average="macro") if y_bin.shape[1] > 1 else 0.5

    model_output.parent.mkdir(parents=True, exist_ok=True)
    with open(model_output, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model saved to %s (AUC=%.4f)", model_output, auc)
    return auc


async def main(min_rows: int = 100) -> None:
    from app.config import get_settings
    settings = get_settings()

    X, y = await load_training_data()
    logger.info("Loaded %d training examples", len(X))

    if len(X) < min_rows:
        logger.error("Insufficient training data (%d < %d). Exiting.", len(X), min_rows)
        sys.exit(1)

    model_path = Path(settings.ml_models_path) / settings.ml_strategy_model_file
    auc = train(X, y, model_path)
    logger.info("Training complete. AUC=%.4f", auc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-rows", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(main(min_rows=args.min_rows))
