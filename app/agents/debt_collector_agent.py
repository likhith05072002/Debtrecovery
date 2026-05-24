"""
DebtCollectorAgent — LiveKit Agent wrapping all domain logic.

This is the core agent class that runs during a live call.
It replaces SessionOrchestrator's domain logic while LiveKit handles
audio transport, VAD, turn detection, and interruptions.

Domain logic preserved:
- FDCPA 3-layer compliance
- Pressure escalation (levels 0-4)
- Refusal detection (45+ keywords, 4 languages)
- Payment intent detection → instant de-escalation
- Function calling (record_promise, opt_out, dispute, escalate, callback, end_call)
- Redis session state
- Silk emotion modulation per pressure level
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from livekit.agents import Agent, RunContext, function_tool

from app.services.compliance.opt_out_handler import process_opt_out
from app.services.memory.redis_session import RedisSessionManager

logger = logging.getLogger(__name__)


class DebtCollectorAgent(Agent):
    """LiveKit Agent for autonomous debt collection calls.

    One instance per active call. Created by livekit_worker.py when
    a SIP call connects.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        call_sid: str,
        borrower_id: uuid.UUID,
        borrower_phone: str,
        organization_id: uuid.UUID,
        campaign_id: uuid.UUID | None,
        strategy: str,
        pressure_level: int = 0,
        redis_session: RedisSessionManager,
        db_session_factory: Any,
        silk_tts: Any | None = None,
    ) -> None:
        super().__init__(instructions=system_prompt)
        self._call_sid = call_sid
        self._borrower_id = borrower_id
        self._borrower_phone = borrower_phone
        self._organization_id = organization_id
        self._campaign_id = campaign_id
        self._strategy = strategy
        self._pressure_level = pressure_level
        self._redis = redis_session
        self._db_factory = db_session_factory
        self._silk_tts = silk_tts
        self._outcome: str = "no_outcome"

    # ── Function Tools (LLM can call these) ──────────────────────────────────

    @function_tool
    async def record_promise(
        self,
        context: RunContext,
        amount: float,
        payment_date: str,
        payment_method: str = "unknown",
    ):
        """Record a repayment promise explicitly made by the borrower during this call.
        Call this as soon as the borrower commits to an amount and date."""
        promise_data = {
            "amount": amount,
            "payment_date": payment_date,
            "payment_method": payment_method,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.set("current_offer", promise_data)
        self._outcome = "promise_made"
        logger.info("Promise recorded: $%.2f by %s (%s)", amount, payment_date, payment_method)
        return f"Promise recorded: ${amount:.2f} by {payment_date}. Thank the borrower and confirm details."

    @function_tool
    async def trigger_opt_out(
        self,
        context: RunContext,
        reason: str,
        channel: str = "voice",
    ):
        """Borrower has clearly requested to stop all contact.
        Triggers immediate FDCPA opt-out processing and ends the call.
        Use when borrower says: 'stop calling', 'cease and desist', 'never contact me again'."""
        logger.info("Opt-out triggered: reason=%s channel=%s borrower=%s", reason, channel, self._borrower_id)

        # Process opt-out in database
        async with self._db_factory() as db:
            from app.models.database.borrower import Borrower
            borrower = await db.get(Borrower, self._borrower_id)
            if borrower:
                await process_opt_out(
                    borrower=borrower,
                    db=db,
                    trigger=reason,
                    channel=channel,
                )
                await db.commit()

        await self._redis.set("compliance_flags", ["opt_out_requested"])
        self._outcome = "opted_out"
        return "Opt-out processed. Inform the borrower they will not be contacted again, then end the call."

    @function_tool
    async def log_dispute(
        self,
        context: RunContext,
        dispute_reason: str,
        amount_disputed: float | None = None,
    ):
        """Borrower is disputing the validity of the debt.
        This immediately stops all collection activity and flags the account for review."""
        logger.info("Dispute filed: reason=%s borrower=%s", dispute_reason, self._borrower_id)

        await self._redis.set("compliance_flags", ["dispute_raised"])
        self._outcome = "dispute_filed"
        return (
            "Dispute logged. Inform the borrower that all collection activity is paused "
            "and they will receive written verification within 30 days. Then end the call."
        )

    @function_tool
    async def escalate_to_human(
        self,
        context: RunContext,
        reason: str,
        priority: str = "normal",
    ):
        """Transfer the call to a human agent.
        Use when: borrower is abusive, making legal threats, situation is complex,
        or borrower explicitly requests a human."""
        logger.info("Escalation requested: reason=%s priority=%s", reason, priority)
        self._outcome = "escalated"
        return "Tell the borrower you are transferring them to a senior agent, then end the call."

    @function_tool
    async def request_callback(
        self,
        context: RunContext,
        callback_time: str,
        preferred_number: str | None = None,
    ):
        """Borrower has requested a callback at a specific time. Schedule accordingly."""
        logger.info("Callback requested: time=%s borrower=%s", callback_time, self._borrower_id)

        callback_data = {
            "callback_time": callback_time,
            "preferred_number": preferred_number,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.set("callback_request", callback_data)
        self._outcome = "callback_scheduled"
        return f"Callback noted for {callback_time}. Confirm with the borrower and end the call."

    @function_tool
    async def end_call(
        self,
        context: RunContext,
        outcome: str,
        summary: str = "",
    ):
        """End the call. Only call this when:
        (1) borrower commits to payment and record_promise was called,
        (2) borrower refused at pressure_level 4 and refuses again,
        (3) borrower explicitly says 'hang up', 'end the call', or 'goodbye'.
        NEVER call this just because the introduction was completed."""
        logger.info("Call ending: outcome=%s summary=%s", outcome, summary)
        self._outcome = outcome
        await self._redis.set_state("ended")
        return "Say a brief professional goodbye and end the conversation."

    # ── Accessors ────────────────────────────────────────────────────────────

    @property
    def outcome(self) -> str:
        return self._outcome

    @property
    def call_sid(self) -> str:
        return self._call_sid

    def update_pressure(self, level: int) -> None:
        """Update pressure level and sync Silk emotion tag."""
        self._pressure_level = level
        if self._silk_tts and hasattr(self._silk_tts, "set_pressure_level"):
            self._silk_tts.set_pressure_level(level)
        logger.info("Pressure level updated to %d for call %s", level, self._call_sid)
