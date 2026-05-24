"""
LiveKit Agent Worker — entrypoint for the voice agent process.

Runs as a separate process from FastAPI. Connects to LiveKit Cloud,
receives SIP call dispatches, and runs DebtCollectorAgent for each call.

Start:
    python -m app.agents.livekit_worker dev      # development (hot reload)
    python -m app.agents.livekit_worker start     # production

Required env vars:
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    OPENAI_API_KEY, DEEPGRAM_API_KEY
    SILK_API_KEY (or ELEVENLABS_API_KEY for fallback)
    DATABASE_URL, REDIS_URL
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

from livekit.agents import AgentSession, JobContext, cli, inference
from livekit.agents import AgentServer
from livekit.plugins import silero

from app.agents.debt_collector_agent import DebtCollectorAgent
from app.config import get_settings
from app.models.database.base import AsyncSessionLocal
from app.services.compliance.fdcpa_guard import (
    check_agent_response,
    check_borrower_speech,
    pre_call_compliance_check,
)
from app.services.llm.prompt_builder import BorrowerContext, CampaignContext, build_system_prompt
from app.services.memory.redis_session import RedisSessionManager
from app.services.memory.vector_store import get_vector_store
from app.services.ml.strategy_engine import get_strategy_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

# ── LiveKit Agent Server ─────────────────────────────────────────────────────

server = AgentServer()


@asynccontextmanager
async def get_db_session():
    """Async context manager for database sessions in the worker process."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@server.sip_session()
async def handle_sip_call(ctx: JobContext) -> None:
    """Handle an incoming SIP call dispatched by LiveKit.

    Flow:
    1. Extract call metadata from room/participant metadata
    2. Load borrower + campaign from database
    3. Run FDCPA pre-call compliance check
    4. Select ML strategy
    5. Retrieve conversation memory from vector store
    6. Build system prompt
    7. Create DebtCollectorAgent with Silk TTS
    8. Wire compliance hooks
    9. Start the call
    """
    logger.info("SIP call received: room=%s", ctx.room.name)

    # ── 1. Extract metadata ──────────────────────────────────────────────────
    room_metadata = json.loads(ctx.room.metadata or "{}")
    call_sid = room_metadata.get("call_sid", ctx.room.name)
    borrower_id = room_metadata.get("borrower_id")
    campaign_id = room_metadata.get("campaign_id")
    organization_id = room_metadata.get("organization_id")
    strategy_hint = room_metadata.get("strategy_hint")
    follow_up_context = room_metadata.get("follow_up_context", "")

    if not borrower_id:
        logger.error("No borrower_id in room metadata — cannot proceed")
        return

    borrower_id = uuid.UUID(borrower_id)
    campaign_id = uuid.UUID(campaign_id) if campaign_id else None
    organization_id = uuid.UUID(organization_id) if organization_id else None

    # ── 2. Load borrower + campaign from DB ──────────────────────────────────
    async with get_db_session() as db:
        from app.models.database.borrower import Borrower
        from app.models.database.campaign import Campaign

        borrower = await db.get(Borrower, borrower_id)
        if not borrower:
            logger.error("Borrower %s not found", borrower_id)
            return

        campaign = await db.get(Campaign, campaign_id) if campaign_id else None

        # ── 3. FDCPA pre-call compliance ─────────────────────────────────────
        try:
            await pre_call_compliance_check(borrower, db)
        except Exception as exc:
            logger.error("FDCPA pre-call check failed: %s", exc)
            return

        # ── 4. ML strategy selection ─────────────────────────────────────────
        strategy_engine = get_strategy_engine()
        if strategy_hint:
            strategy = strategy_hint
        else:
            decision = strategy_engine.predict(borrower)
            strategy = decision.strategy

        # ── 5. Retrieve conversation memory ──────────────────────────────────
        vector_store = get_vector_store()
        retrieved_context = await vector_store.retrieve_context(
            borrower_id=str(borrower_id),
            query=f"Previous calls with {borrower.first_name}",
        )

        # ── 6. Build system prompt ───────────────────────────────────────────
        from app.utils.crypto import decrypt_pii

        borrower_ctx = BorrowerContext(
            borrower_id=borrower.id,
            first_name=borrower.first_name or "there",
            last_name=borrower.last_name,
            phone=decrypt_pii(borrower.phone_e164),
            original_creditor=borrower.original_creditor or "your creditor",
            principal_amount=float(borrower.principal_amount),
            current_balance=float(borrower.current_balance),
            days_past_due=borrower.days_past_due,
            debt_type=borrower.debt_type or "account",
            preferred_language=borrower.preferred_language,
            engagement_score=float(borrower.engagement_score),
            avoidance_score=float(borrower.avoidance_score),
            repayment_likelihood=float(borrower.repayment_likelihood),
            sentiment_trend=borrower.sentiment_trend,
            pressure_level=0,
        )

        campaign_ctx = CampaignContext(
            campaign_id=campaign_id,
            strategy_type=strategy,
            settlement_floor_pct=float(campaign.settlement_floor_pct) if campaign else 0.5,
            max_attempts=campaign.max_attempts if campaign else 5,
        )

        system_prompt = build_system_prompt(
            borrower=borrower_ctx,
            campaign=campaign_ctx,
            retrieved_context=retrieved_context,
            follow_up_context=follow_up_context,
            agency_name=settings.agency_name,
            agent_name=settings.agent_name,
        )

    # ── 7. Create TTS (Silk with ElevenLabs fallback) ────────────────────────
    silk_tts = None
    if settings.silk_api_key:
        from app.services.tts.silk_livekit_plugin import SilkTTS
        silk_tts = SilkTTS(
            api_key=settings.silk_api_key,
            voice_id=settings.silk_default_voice,
            model_id=settings.silk_model_id,
            language=borrower_ctx.preferred_language,
            sample_rate=settings.silk_sample_rate,
        )
        tts_provider = silk_tts
    else:
        # Fallback to ElevenLabs via LiveKit plugin
        tts_provider = inference.TTS(
            "elevenlabs/eleven_turbo_v2",
            voice=settings.elevenlabs_voice_id,
        )

    # ── 8. Create LiveKit session ────────────────────────────────────────────
    # Import turn detector
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        turn_detection = MultilingualModel()
    except ImportError:
        turn_detection = None
        logger.warning("Turn detector not available — using VAD-only endpointing")

    redis_session = RedisSessionManager(call_sid)
    await redis_session.initialize({
        "borrower_id": str(borrower_id),
        "strategy": strategy,
        "organization_id": str(organization_id) if organization_id else "",
    })

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=inference.STT("deepgram/nova-3", language="multi"),
        llm=inference.LLM("openai/gpt-4o"),
        tts=tts_provider,
        turn_detection=turn_detection,
    )

    # ── 9. Create agent ──────────────────────────────────────────────────────
    agent = DebtCollectorAgent(
        system_prompt=system_prompt,
        call_sid=call_sid,
        borrower_id=borrower_id,
        borrower_phone=borrower_ctx.phone,
        organization_id=organization_id,
        campaign_id=campaign_id,
        strategy=strategy,
        redis_session=redis_session,
        db_session_factory=get_db_session,
        silk_tts=silk_tts,
    )

    # ── 10. Wire compliance hooks ────────────────────────────────────────────

    @session.on("user_speech_committed")
    async def on_user_speech(ev):
        """FDCPA Layer 3: Scan borrower speech for opt-out/dispute triggers."""
        transcript = ev.transcript if hasattr(ev, "transcript") else str(ev)
        if not transcript:
            return

        actions = check_borrower_speech(transcript)
        for action in actions:
            if action.action_type == "opt_out":
                logger.info("Auto opt-out triggered by borrower speech: %s", action.trigger)
                await agent.trigger_opt_out(
                    context=None, reason=action.trigger, channel="voice"
                )
            elif action.action_type == "dispute":
                logger.info("Dispute detected in borrower speech: %s", action.trigger)
                await agent.log_dispute(
                    context=None, dispute_reason=action.trigger
                )

        # Track turn count
        turn_count = int(await redis_session.get("turn_count") or "0")
        await redis_session.set("turn_count", str(turn_count + 1))

    @session.on("agent_speech_created")
    def on_agent_speech(ev):
        """FDCPA Layer 2: Filter agent output before TTS synthesis."""
        text = ev.text if hasattr(ev, "text") else str(ev)
        if not text:
            return

        guard = check_agent_response(text)
        if guard.blocked:
            logger.warning("FDCPA guard blocked agent response: %s → %s", guard.reason, text[:60])
            # Cancel the speech event to prevent TTS
            if hasattr(ev, "cancel"):
                ev.cancel()

    @session.on("agent_session_ended")
    async def on_session_ended(ev):
        """Trigger post-call analysis pipeline via Celery."""
        outcome = agent.outcome
        logger.info("Call ended: call_sid=%s outcome=%s", call_sid, outcome)

        # Trigger async post-call analysis
        try:
            from app.workers.analytics_tasks import post_call_analysis
            post_call_analysis.delay(call_sid, outcome)
        except Exception as exc:
            logger.error("Failed to trigger post-call analysis: %s", exc)

        # Cleanup Redis session (let post-call task read it first)
        # Session TTL handles cleanup automatically (4 hours)

    # ── 11. Start the call ───────────────────────────────────────────────────
    await session.start(agent=agent, room=ctx.room)

    # Deliver greeting + mini-miranda
    lang = borrower_ctx.preferred_language
    greeting_instruction = (
        f"Greet {borrower_ctx.first_name} and deliver the FDCPA mini-miranda disclosure. "
        f"You are {settings.agent_name} from {settings.agency_name}. "
        f"The borrower owes {borrower_ctx.original_creditor}. "
        f"This is a required legal disclosure — deliver it completely without pausing. "
        f"Speak in {'Hindi' if lang == 'hi' else 'Kannada' if lang == 'kn' else 'Telugu' if lang == 'te' else 'English'}."
    )
    await session.generate_reply(instructions=greeting_instruction)

    logger.info("Agent started for call %s, borrower %s, strategy=%s",
                call_sid, borrower_id, strategy)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli.run_app(server)
