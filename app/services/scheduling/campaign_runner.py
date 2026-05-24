"""
Campaign runner — dispatches pending scheduled calls to Celery workers.
Run periodically by Celery Beat (every minute).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.campaign import CallSchedule

logger = logging.getLogger(__name__)


async def dispatch_pending_calls(db: AsyncSession, limit: int = 50) -> int:
    """
    Find all pending scheduled calls whose scheduled_at <= now and dispatch
    them as Celery tasks. Returns the number of calls dispatched.
    """
    from app.workers.call_tasks import place_outbound_call

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CallSchedule)
        .where(CallSchedule.status == "pending", CallSchedule.scheduled_at <= now)
        .order_by(CallSchedule.priority.asc(), CallSchedule.scheduled_at.asc())
        .limit(limit)
    )
    pending = result.scalars().all()

    dispatched = 0
    for schedule in pending:
        try:
            task = place_outbound_call.apply_async(
                kwargs={
                    "borrower_id": str(schedule.borrower_id),
                    "campaign_id": str(schedule.campaign_id) if schedule.campaign_id else None,
                    "strategy_hint": schedule.strategy_hint,
                    "schedule_id": str(schedule.id),
                },
                queue="realtime",
            )
            schedule.status = "dispatched"
            schedule.celery_task_id = task.id
            dispatched += 1
        except Exception as exc:
            logger.error("Failed to dispatch schedule %s: %s", schedule.id, exc)

    if dispatched:
        logger.info("Dispatched %d calls from campaign runner", dispatched)

    return dispatched
