"""Post-call analytics Celery tasks."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.analytics_tasks.post_call_analysis")
def post_call_analysis(call_sid: str, outcome: str) -> dict:
    """
    Run after every call ends:
    1. Update call record with final outcome + latency averages
    2. Persist conversation turns from Redis to PostgreSQL
    3. Log behavioral events
    4. Update borrower scores
    5. Store ML training record
    6. Schedule next call retry if needed
    """
    async def _run():
        from app.models.database.base import AsyncSessionLocal
        from app.models.database.call import Call
        from app.models.database.borrower import Borrower
        from app.models.database.conversation import ConversationTurn, BehavioralEvent, RepaymentPromise
        from app.services.profiling.borrower_scorer import update_borrower_scores
        from app.services.ml.outcome_tracker import record_call_outcome
        from app.services.memory.redis_session import RedisSessionManager
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            # Look up call by Twilio SID
            result = await db.execute(select(Call).where(Call.twilio_call_sid == call_sid))
            call = result.scalar_one_or_none()
            if not call:
                logger.warning("post_call_analysis: call not found for SID %s", call_sid)
                return

            borrower = await db.get(Borrower, call.borrower_id)
            if not borrower:
                return

            # Finalize call record
            call.outcome = outcome
            call.ended_at = datetime.now(timezone.utc)
            if call.started_at and call.ended_at:
                call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())

            # Persist conversation turns from Redis
            session = RedisSessionManager(call_sid)
            history = await session.get_history()
            for idx, turn in enumerate(history):
                ct = ConversationTurn(
                    call_id=call.id,
                    turn_index=idx + 1,
                    speaker=turn.get("speaker", "unknown"),
                    raw_transcript=turn.get("text", ""),
                    stt_confidence=turn.get("confidence"),
                    intent=turn.get("intent"),
                    sentiment_score=turn.get("sentiment"),
                    entities=turn.get("entities", {}),
                )
                db.add(ct)

            # Log behavioral events
            if outcome == "promise_made":
                event = BehavioralEvent(
                    borrower_id=borrower.id,
                    call_id=call.id,
                    event_type="promise_made",
                )
                db.add(event)
                # Retrieve promise details from Redis session
                import json
                session_data = await session.get_all()
                current_offer_raw = session_data.get("current_offer", "{}")
                try:
                    offer = json.loads(current_offer_raw)
                    if offer.get("amount") and offer.get("payment_date"):
                        from datetime import date
                        promise = RepaymentPromise(
                            borrower_id=borrower.id,
                            call_id=call.id,
                            promised_amount=offer["amount"],
                            promised_date=datetime.fromisoformat(offer["payment_date"]),
                            method=offer.get("payment_method", "unknown"),
                        )
                        db.add(promise)
                        call.promise_amount = offer["amount"]
                except Exception:
                    pass

            elif outcome in ("hung_up_early", "no_answer", "refused"):
                event = BehavioralEvent(
                    borrower_id=borrower.id,
                    call_id=call.id,
                    event_type=outcome,
                )
                db.add(event)

            # Update borrower call counters
            borrower.total_calls += 1
            if outcome not in ("no_answer", "voicemail", "busy", "failed"):
                borrower.successful_contacts += 1

            # Update behavioral scores (async compute)
            await update_borrower_scores(str(borrower.id), db)

            # Record ML training example
            await record_call_outcome(call=call, borrower=borrower, db=db)

            await db.commit()

            # Clean up Redis session
            await session.delete()

            logger.info("Post-call analysis complete: call_sid=%s outcome=%s", call_sid, outcome)
            return {"status": "ok", "call_id": str(call.id), "outcome": outcome}

    return asyncio.run(_run())



@celery_app.task(name="app.workers.analytics_tasks.refresh_all_borrower_scores")
def refresh_all_borrower_scores() -> dict:
    """Nightly job: recompute scores for all active borrowers."""
    async def _run():
        from app.models.database.base import AsyncSessionLocal
        from app.models.database.borrower import Borrower
        from app.services.profiling.borrower_scorer import update_borrower_scores
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Borrower.id).where(Borrower.opted_out == False))
            ids = [str(row[0]) for row in result.all()]
            for bid in ids:
                await update_borrower_scores(bid, db)
            await db.commit()
            return {"updated": len(ids)}

    return asyncio.run(_run())
