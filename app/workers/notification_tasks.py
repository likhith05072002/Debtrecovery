"""Notification and alerting tasks."""
from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.notification_tasks.send_compliance_alert")
def send_compliance_alert(borrower_id: str, event_type: str, severity: str) -> None:
    """Send an alert when a compliance violation occurs."""
    logger.warning(
        "COMPLIANCE ALERT: borrower=%s event=%s severity=%s",
        borrower_id, event_type, severity
    )
    # TODO: integrate with PagerDuty / Slack / email


@celery_app.task(name="app.workers.notification_tasks.send_daily_report")
def send_daily_report() -> None:
    """Send daily summary report to operations team."""
    logger.info("Daily report task triggered")
    # TODO: generate and send report
