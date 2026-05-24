"""
Celery application instance and Beat schedule.

Queues:
  realtime — post-call analytics, high priority (5-minute SLA)
  batch    — ML model training, reporting (best-effort)

Beat schedules:
  Every 60s: dispatch pending calls from call_schedule table
  Every 24h: trigger borrower score refresh
  Weekly:    trigger ML model retraining
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "debtcollector",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.call_tasks",
        "app.workers.analytics_tasks",
        "app.workers.ml_tasks",
        "app.workers.notification_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.call_tasks.*": {"queue": "realtime"},
        "app.workers.analytics_tasks.*": {"queue": "realtime"},
        "app.workers.ml_tasks.*": {"queue": "batch"},
        "app.workers.notification_tasks.*": {"queue": "batch"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # Fair dispatch for long-running tasks
    task_soft_time_limit=300,       # 5 min soft limit
    task_time_limit=600,            # 10 min hard limit
)

celery_app.conf.beat_schedule = {
    "dispatch-pending-calls": {
        "task": "app.workers.call_tasks.dispatch_campaign_calls",
        "schedule": 60.0,   # every 60 seconds
        "options": {"queue": "realtime"},
    },
    "refresh-borrower-scores-daily": {
        "task": "app.workers.analytics_tasks.refresh_all_borrower_scores",
        "schedule": crontab(hour=2, minute=0),  # 2 AM UTC daily
        "options": {"queue": "batch"},
    },
    "retrain-strategy-model-weekly": {
        "task": "app.workers.ml_tasks.retrain_strategy_model",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday 3 AM
        "options": {"queue": "batch"},
    },
}
