"""Celery tasks for outbound call dispatch."""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.call_tasks.place_outbound_call",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def place_outbound_call(
    self,
    borrower_id: str,
    campaign_id: str | None = None,
    strategy_hint: str | None = None,
    schedule_id: str | None = None,
) -> dict:
    """Initiate an outbound call for a borrower."""
    async def _run():
        from app.models.database.base import make_worker_session
        from app.models.database.borrower import Borrower
        from app.services.telephony.call_controller import initiate_outbound_call
        from app.services.compliance.fdcpa_guard import FDCPAViolationError

        async with make_worker_session()() as db:
            borrower = await db.get(Borrower, uuid.UUID(borrower_id))
            if not borrower:
                logger.error("Borrower %s not found for call task", borrower_id)
                return {"status": "error", "reason": "borrower_not_found"}

            try:
                call = await initiate_outbound_call(
                    borrower=borrower,
                    db=db,
                    campaign_id=uuid.UUID(campaign_id) if campaign_id else None,
                    strategy_hint=strategy_hint,
                )
                await db.commit()
                return {"status": "initiated", "call_id": str(call.id), "twilio_sid": call.twilio_call_sid}
            except FDCPAViolationError as exc:
                logger.info("FDCPA compliance blocked call for borrower %s: %s", borrower_id, exc.reason)
                return {"status": "blocked", "reason": exc.reason}
            except Exception as exc:
                logger.error("Call dispatch failed for borrower %s: %s", borrower_id, exc)
                raise self.retry(exc=exc)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


@celery_app.task(name="app.workers.call_tasks.dispatch_campaign_calls")
def dispatch_campaign_calls() -> dict:
    """Dispatch all pending scheduled calls — run by Celery Beat every 60s."""
    async def _run():
        from app.models.database.base import make_worker_session
        from app.services.scheduling.campaign_runner import dispatch_pending_calls

        async with make_worker_session()() as db:
            count = await dispatch_pending_calls(db)
            await db.commit()
            return {"dispatched": count}

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_run())
    finally:
        loop.close()
    logger.info("Campaign runner dispatched %d calls", result.get("dispatched", 0))
    return result
