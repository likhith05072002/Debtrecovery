"""
Twilio Media Streams WebSocket handler — the real-time audio pipeline.

This is the most latency-critical code in the system. It:
1. Accepts the Twilio WebSocket connection
2. Decodes incoming mulaw audio and forwards to Deepgram STT
3. Routes STT final transcripts to SessionOrchestrator
4. Sends TTS audio chunks back to Twilio

Audio format: Twilio sends/receives mulaw 8kHz (G.711 µ-law), base64-encoded.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.session_orchestrator import SessionOrchestrator
from app.models.database.base import AsyncSessionLocal
from app.services.follow_up.followup import build_follow_up_plan
from app.services.llm.prompt_builder import BorrowerContext, CampaignContext
from app.services.follow_up.follow_up_brief import build_follow_up_brief
from app.services.memory.redis_session import get_call_setup_metadata
from app.services.ml.strategy_engine import get_strategy_engine
from app.services.stt.deepgram_client import DeepgramStreamingClient
from app.utils.audio_utils import decode_twilio_payload, encode_twilio_payload, mulaw_to_pcm16

logger = logging.getLogger(__name__)
router = APIRouter()

# Active sessions: call_sid → SessionOrchestrator
_active_sessions: dict[str, SessionOrchestrator] = {}


@router.websocket("/ws/media/{call_sid}")
async def media_stream_handler(websocket: WebSocket, call_sid: str) -> None:
    """
    Handle a Twilio Media Streams WebSocket connection.

    Message types from Twilio:
      connected  — WebSocket established
      start      — Call metadata (stream SID, account SID, call SID)
      media      — Audio payload (base64 mulaw)
      stop       — Call ended
    """
    await websocket.accept()
    logger.info("Media stream WebSocket connected: call_sid=%s", call_sid)

    orchestrator: SessionOrchestrator | None = None
    deepgram: DeepgramStreamingClient | None = None
    stream_sid: str = ""
    _post_call_done: bool = False   # guard against double-run
    _calibration_frames: int = 0    # count frames for noise floor calibration

    # ── Callback: send audio chunk back to Twilio ─────────────────────────────
    async def send_audio_to_twilio(mulaw_chunk: bytes) -> None:
        if websocket.client_state.value == 1:   # CONNECTED
            # Feed outgoing audio to AEC as echo reference
            if orchestrator is not None:
                pcm_ref = mulaw_to_pcm16(mulaw_chunk)
                orchestrator._barge_in.feed_echo_reference(pcm_ref)
            payload = encode_twilio_payload(mulaw_chunk)
            msg = json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            })
            await websocket.send_text(msg)

    # ── Callback: flush Twilio's queued audio buffer ───────────────────────────
    async def clear_twilio_buffer() -> None:
        if websocket.client_state.value == 1 and stream_sid:  # CONNECTED
            await websocket.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))

    # ── Callback: call ended (AI-triggered) ───────────────────────────────────
    async def on_call_ended(outcome: str) -> None:
        nonlocal _post_call_done
        logger.info("Call ended: call_sid=%s outcome=%s", call_sid, outcome)
        _post_call_done = True
        # Save latency averages NOW before the task runs (avoids race with finally block)
        if orchestrator:
            latencies = orchestrator.get_average_latencies()
            await orchestrator._session.set("latency_summary", latencies)
        asyncio.create_task(_run_post_call_analysis(call_sid, outcome))

    try:
        async for raw_message in websocket.iter_text():
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event_type = message.get("event")

            # ── connected ────────────────────────────────────────────────────
            if event_type == "connected":
                logger.debug("Twilio media stream connected")

            # ── start ────────────────────────────────────────────────────────
            elif event_type == "start":
                start_data = message.get("start", {})
                stream_sid = start_data.get("streamSid", "")
                custom_params = start_data.get("customParameters", {})
                actual_call_sid = custom_params.get("callSid", call_sid)

                # Look up call + borrower from database
                orchestrator, deepgram = await _initialize_call_session(
                    call_sid=actual_call_sid,
                    stream_sid=stream_sid,
                    send_audio_fn=send_audio_to_twilio,
                    on_call_end_fn=on_call_ended,
                    clear_buffer_fn=clear_twilio_buffer,
                )
                # Enable echo cancellation on the barge-in detector
                if orchestrator:
                    orchestrator._barge_in.enable_aec()

            # ── media ────────────────────────────────────────────────────────
            elif event_type == "media":
                if deepgram is None or orchestrator is None:
                    continue

                media = message.get("media", {})
                payload = media.get("payload", "")
                if not payload:
                    continue

                # Decode base64 mulaw → PCM for Deepgram and barge-in detection
                mulaw_bytes = decode_twilio_payload(payload)
                pcm_bytes = mulaw_to_pcm16(mulaw_bytes)

                # Noise floor calibration (first ~50 frames ≈ 1s of audio)
                if _calibration_frames < 50:
                    orchestrator._barge_in.calibrate(pcm_bytes)
                    _calibration_frames += 1

                # Barge-in detection using orchestrator's unified detector
                # (detector internally checks is_agent_speaking via its own state)
                if orchestrator._barge_in.detect(pcm_bytes):
                    _t_interrupt = time.monotonic()
                    # Interrupt TTS + clear Twilio buffer immediately (sub-100ms)
                    await orchestrator._interrupt_tts()
                    # Mark barge-in so on_transcript handles yield + LLM (no double-yield)
                    orchestrator.mark_audio_barge_in()
                    # Instrument
                    from app.monitoring.metrics import barge_in_triggered, barge_in_latency
                    barge_in_triggered.labels(path="audio_level").inc()
                    barge_in_latency.observe((time.monotonic() - _t_interrupt) * 1000)
                    logger.debug("Barge-in detected (audio-level) for call %s", call_sid)

                # Forward audio to Deepgram
                await deepgram.send_audio(pcm_bytes)

            # ── stop ─────────────────────────────────────────────────────────
            elif event_type == "stop":
                logger.info("Media stream stop received: call_sid=%s", call_sid)
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: call_sid=%s", call_sid)
    except Exception as exc:
        logger.error("Media stream error for %s: %s", call_sid, exc, exc_info=True)
    finally:
        # Cleanup
        if deepgram:
            await deepgram.close()
        if orchestrator:
            # Persist latency averages to Redis before orchestrator closes
            latencies = orchestrator.get_average_latencies()
            await orchestrator._session.set("latency_summary", latencies)
            await orchestrator.close()
        _active_sessions.pop(call_sid, None)
        logger.info("Media stream session cleaned up: call_sid=%s", call_sid)
        # Always persist transcript — even if human hangs up without AI end_call trigger
        if not _post_call_done:
            asyncio.create_task(_run_post_call_analysis(call_sid, "completed"))


async def _initialize_call_session(
    call_sid: str,
    stream_sid: str,
    send_audio_fn,
    on_call_end_fn,
    clear_buffer_fn=None,
) -> tuple[SessionOrchestrator, DeepgramStreamingClient]:
    """
    Load borrower + call from database, build contexts, initialize orchestrator + Deepgram.
    """
    from sqlalchemy import select
    from app.models.database.call import Call
    from app.models.database.borrower import Borrower
    from app.models.database.campaign import Campaign
    from app.utils.crypto import decrypt_pii

    async with AsyncSessionLocal() as db:
        # Look up call by Twilio SID
        result = await db.execute(
            select(Call).where(Call.twilio_call_sid == call_sid)
        )
        call = result.scalar_one_or_none()

        if not call:
            raise ValueError(f"Call not found for SID: {call_sid}")

        borrower = await db.get(Borrower, call.borrower_id)
        if not borrower:
            raise ValueError(f"Borrower not found for call {call_sid}")

        campaign = await db.get(Campaign, call.campaign_id) if call.campaign_id else None
        setup_metadata = await get_call_setup_metadata(call_sid)

        # Determine strategy
        engine = get_strategy_engine()
        strategy_decision = engine.select_strategy(borrower)
        strategy = (
            setup_metadata.get("strategy_hint")
            if setup_metadata and setup_metadata.get("strategy_hint")
            else strategy_decision.strategy
        )

        follow_up_brief = None
        if setup_metadata and setup_metadata.get("follow_up_enabled"):
            follow_up_brief = await build_follow_up_brief(
                db,
                str(borrower.id),
                setup_metadata.get("follow_up_source_call_id"),
            )

        # Build prompt contexts
        borrower_ctx = BorrowerContext(
            borrower_id=str(borrower.id),
            first_name=borrower.first_name or "there",
            account_last4=str(borrower.account_number_hash or "XXXX")[-4:],
            current_balance=borrower.current_balance,
            principal_amount=borrower.principal_amount,
            days_past_due=borrower.days_past_due,
            debt_type=borrower.debt_type or "general",
            original_creditor=borrower.original_creditor or "the original creditor",
            total_calls=borrower.total_calls,
            successful_contacts=borrower.successful_contacts,
            last_outcome=None,
            engagement_score=float(borrower.engagement_score or 0.5),
            avoidance_score=float(borrower.avoidance_score or 0.0),
            sentiment_trend=borrower.sentiment_trend or "neutral",
            promise_kept_count=0,
            promise_made_count=0,
            preferred_language=borrower.preferred_language or "en",
        )

        campaign_ctx = CampaignContext(
            strategy_type=strategy,
            settlement_floor_pct=float(campaign.settlement_floor_pct if campaign else 0.5),
            min_payment_monthly=None,
            max_extension_days=30,
        )

        follow_up_context = ""
        follow_up_opening_line = ""
        follow_up_first_turn_instruction = ""
        if follow_up_brief:
            follow_up_plan = build_follow_up_plan(follow_up_brief)
            follow_up_context = follow_up_plan.context_block
            follow_up_opening_line = follow_up_plan.spoken_opening
            follow_up_first_turn_instruction = follow_up_plan.first_turn_instruction

        # Update call record with stream SID and answered_at
        call.answered_at = datetime.now(timezone.utc)
        call.status = "in-progress"
        await db.commit()

    # Initialize orchestrator
    orchestrator = SessionOrchestrator(
        call_sid=call_sid,
        borrower_ctx=borrower_ctx,
        campaign_ctx=campaign_ctx,
        follow_up_context=follow_up_context,
        follow_up_opening_line=follow_up_opening_line,
        follow_up_first_turn_instruction=follow_up_first_turn_instruction,
        on_audio_chunk=send_audio_fn,
        on_call_end=on_call_end_fn,
        on_clear_buffer=clear_buffer_fn,
    )
    await orchestrator.initialize(strategy=strategy)
    _active_sessions[call_sid] = orchestrator

    # Initialize Deepgram STT
    deepgram = DeepgramStreamingClient(
        on_transcript=orchestrator.on_transcript,
        language=borrower_ctx.preferred_language,
    )
    await deepgram.connect()

    return orchestrator, deepgram


async def _run_post_call_analysis(call_sid: str, outcome: str) -> None:
    """
    Persist conversation turns from Redis → PostgreSQL and update call/borrower records.
    Runs inline (no Celery) so transcripts are always saved.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models.database.base import AsyncSessionLocal
    from app.models.database.call import Call
    from app.models.database.borrower import Borrower
    from app.models.database.conversation import ConversationTurn, BehavioralEvent
    from app.services.memory.redis_session import RedisSessionManager

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Call).where(Call.twilio_call_sid == call_sid))
            call = result.scalar_one_or_none()
            if not call:
                logger.warning("post_call_analysis: call not found for SID %s", call_sid)
                return

            borrower = await db.get(Borrower, call.borrower_id)

            # Finalize call record
            call.outcome = outcome
            call.ended_at = datetime.now(timezone.utc)
            if call.started_at and call.ended_at:
                call.duration_seconds = int((call.ended_at - call.started_at).total_seconds())

            # Persist conversation turns from Redis → DB
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

            call.turn_count = len(history)

            # Persist latency averages from orchestrator
            import json as _json
            raw_latency = await session.get("latency_summary")
            if raw_latency:
                try:
                    latency = _json.loads(raw_latency) if isinstance(raw_latency, str) else raw_latency
                    call.llm_latency_avg_ms = latency.get("llm_latency_avg_ms")
                    call.tts_latency_avg_ms = latency.get("tts_latency_avg_ms")
                except Exception:
                    pass

            # Persist pressure escalation events
            import json as _json
            pressure_log_key = f"session:{call_sid}:pressure_log"
            raw_events = await session._r.lrange(pressure_log_key, 0, -1)
            for raw in raw_events:
                try:
                    ev = _json.loads(raw)
                    db.add(BehavioralEvent(
                        borrower_id=call.borrower_id,
                        call_id=call.id,
                        event_type="pressure_escalation",
                        event_data={"level": ev["level"], "trigger": ev.get("trigger", "")},
                        detected_at=datetime.fromisoformat(ev["ts"]),
                    ))
                except Exception:
                    pass
            await session._r.delete(pressure_log_key)

            # Update borrower counters
            if borrower:
                borrower.total_calls += 1
                if outcome not in ("no_answer", "voicemail", "busy", "failed"):
                    borrower.successful_contacts += 1

            await db.commit()
            await session.delete()
            logger.info("Post-call analysis saved: call_sid=%s turns=%d outcome=%s", call_sid, len(history), outcome)

            # Launch AI intelligence analysis (non-blocking — runs after commit)
            if history and call.id:
                asyncio.create_task(_run_ai_intelligence(call.id, call.borrower_id, borrower, history))

    except Exception as exc:
        logger.error("Post-call analysis failed for %s: %s", call_sid, exc, exc_info=True)


async def _run_ai_intelligence(
    call_id: uuid.UUID,
    borrower_id: uuid.UUID,
    borrower: object,
    history: list[dict],
) -> None:
    """Run GPT-4o intelligence analysis on the completed AI call transcript."""
    from app.models.database.base import AsyncSessionLocal
    from app.models.database.call_analysis import CallAnalysis
    from app.agents.call_intelligence.analyzer import CallAnalyzer
    from datetime import datetime, timezone

    try:
        # Build plain-text transcript from conversation history
        lines = []
        for turn in history:
            speaker = "Agent" if turn.get("speaker") == "agent" else "Borrower"
            text = turn.get("text", "").strip()
            if text:
                lines.append(f"{speaker}: {text}")
        transcript_text = "\n".join(lines)
        if not transcript_text:
            return

        borrower_context = {
            "name": getattr(borrower, "first_name", "Unknown") if borrower else "Unknown",
            "balance": str(getattr(borrower, "current_balance", "0")),
            "days_past_due": getattr(borrower, "days_past_due", 0),
            "debt_type": getattr(borrower, "debt_type", "general"),
        }

        analyzer = CallAnalyzer()

        async with AsyncSessionLocal() as db:
            # Create pending analysis record
            analysis = CallAnalysis(
                ai_call_id=call_id,
                borrower_id=borrower_id,
                transcription_status="completed",
                analysis_status="processing",
                transcript_text=transcript_text,
            )
            db.add(analysis)
            await db.commit()
            await db.refresh(analysis)

            analysis_id = analysis.id

        # Run GPT-4o analysis (outside DB session to avoid long-held connection)
        result = await analyzer.analyze_transcript(transcript_text, borrower_context)

        async with AsyncSessionLocal() as db:
            analysis = await db.get(CallAnalysis, analysis_id)
            if analysis:
                analysis.overall_sentiment = result.overall_sentiment
                analysis.sentiment_score = result.sentiment_score
                analysis.willingness_to_pay = result.willingness_to_pay
                analysis.payment_intent_score = result.payment_intent_score
                analysis.key_points = result.key_points
                analysis.borrower_characterization = result.borrower_characterization
                analysis.repayment_probability = result.repayment_probability
                analysis.repayment_probability_reason = result.repayment_probability_reason
                analysis.recommended_strategy = result.recommended_strategy
                analysis.next_call_talking_points = result.next_call_talking_points
                analysis.analysis_model = result.model_used
                analysis.analysis_status = "completed"
                analysis.analysis_completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("AI intelligence analysis complete for call %s", call_id)

    except Exception as exc:
        logger.error("AI intelligence analysis failed for call %s: %s", call_id, exc, exc_info=True)
        try:
            from app.models.database.base import AsyncSessionLocal
            from app.models.database.call_analysis import CallAnalysis
            from sqlalchemy import select
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(CallAnalysis).where(CallAnalysis.ai_call_id == call_id)
                )
                analysis = result.scalar_one_or_none()
                if analysis:
                    analysis.analysis_status = "failed"
                    analysis.analysis_error = str(exc)[:500]
                    await db.commit()
        except Exception:
            pass
