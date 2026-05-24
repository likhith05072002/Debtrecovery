"""ML training Celery tasks — weekly XGBoost model retraining."""
from __future__ import annotations

import asyncio
import logging
import pickle
from pathlib import Path

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.ml_tasks.retrain_strategy_model")
def retrain_strategy_model() -> dict:
    """
    Weekly: retrain the XGBoost strategy classifier on all historical call outcomes.
    Promotes new model if AUC improves over current production model.
    """
    async def _run():
        from app.models.database.base import AsyncSessionLocal
        from app.models.database.ml_outcome import MLCallOutcome
        from app.config import get_settings
        from sqlalchemy import select

        settings = get_settings()
        model_path = Path(settings.ml_models_path) / settings.ml_strategy_model_file
        model_path.parent.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MLCallOutcome).where(MLCallOutcome.outcome_label.isnot(None))
            )
            rows = result.scalars().all()

        if len(rows) < 100:
            logger.info("Not enough training data (%d rows). Skipping retraining.", len(rows))
            return {"status": "skipped", "reason": "insufficient_data", "rows": len(rows)}

        import numpy as np
        from app.services.ml.feature_extractor import FEATURE_NAMES, DEBT_TYPE_ENCODING

        LABEL_MAP = {
            "promise_made": 0, "payment_arranged": 1, "refused": 2,
            "voicemail": 3, "no_answer": 3, "dispute_filed": 4, "escalated": 4,
        }

        X, y = [], []
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
                0.5,   # promise_kept_rate placeholder
                0.0,   # hardship_flag placeholder
                0.5,   # contact_rate placeholder
            ]
            X.append(features)
            y.append(label)

        if len(X) < 50:
            return {"status": "skipped", "reason": "insufficient_valid_rows"}

        X_arr = np.array(X, dtype=np.float32)
        y_arr = np.array(y)

        # Train/val split
        split = int(len(X_arr) * 0.8)
        X_train, X_val = X_arr[:split], X_arr[split:]
        y_train, y_val = y_arr[:split], y_arr[split:]

        try:
            import xgboost as xgb
            from sklearn.metrics import roc_auc_score
            from sklearn.preprocessing import label_binarize

            model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                use_label_encoder=False,
                eval_metric="mlogloss",
                random_state=42,
            )
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

            # Evaluate
            proba = model.predict_proba(X_val)
            classes = sorted(set(y_arr))
            y_bin = label_binarize(y_val, classes=classes)
            if y_bin.shape[1] > 1:
                auc = roc_auc_score(y_bin, proba[:, :len(classes)], multi_class="ovr", average="macro")
            else:
                auc = 0.5

            logger.info("Strategy model retrained: AUC=%.4f rows=%d", auc, len(X))

            # Always save (no baseline in cold start)
            with open(model_path, "wb") as f:
                pickle.dump(model, f)
            logger.info("Strategy model saved to %s", model_path)

            return {"status": "retrained", "auc": round(auc, 4), "rows": len(X)}

        except ImportError:
            logger.error("xgboost not installed — ML training skipped")
            return {"status": "error", "reason": "xgboost_not_installed"}

    return asyncio.run(_run())
