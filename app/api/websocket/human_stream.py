"""
Real-time transcription WebSocket for human-agent calls.

Flow:
  Twilio Media Stream → /ws/human/{call_sid}
  → Deepgram STT (with diarization) → transcript accumulated in Redis
  → On call end → GPT-4o analysis → stored in CallAnalysis
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.models.database.base import AsyncSessionLocal
from app.utils.audio_utils import decode_twilio_payload, mulaw_to_pcm16

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Deepgram client with diarization (separate from AI call client) ───────────

class _HumanDeepgramClient:
    """
    Minimal Deepgram streaming client for human calls.
    Enables diarize=true so speaker IDs come back on each word.
    Calls back on_transcript(text, confidence, speaker_index, start_ms, end_ms).
    """

    WS_URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self, on_turn) -> None:
        self._on_turn = on_turn
        self._ws = None
        self._receiver_task = None
        self._keepalive_task = None
        settings = get_settings()
        self._api_key = settings.deepgram_api_key
        self._model = settings.deepgram_model

    async def connect(self) -> None:
        import websockets
        params = (
            f"?model={self._model}"
            f"&encoding=linear16"
            f"&sample_rate=8000"
            f"&channels=1"
            f"&diarize=true"
            f"&interim_results=false"          # final utterances only for cleaner turns
            f"&smart_format=true"
            f"&punctuate=true"
            f"&language=en-IN"
        )
        headers = {"Authorization": f"Token {self._api_key}"}
        self._ws = await websockets.connect(
            self.WS_URL + params,
            extra_headers=headers,
            ping_interval=5,
            ping_timeout=20,
        )
        self._receiver_task = asyncio.create_task(self._receive_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.debug("Human Deepgram WS connected")

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.send(pcm_bytes)

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
        if self._receiver_task:
            self._receiver_task.cancel()
        if self._keepalive_task:
            self._keepalive_task.cancel()

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(8)
                if self._ws and not self._ws.closed:
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _receive_loop(self) -> None:
        from websockets.exceptions import ConnectionClosed
        try:
            async for message in self._ws:
                await self._handle_message(message)
        except ConnectionClosed:
            pass
        except Exception as exc:
            logger.error("Human Deepgram receiver error: %s", exc)

    async def _handle_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        if data.get("type") != "Results":
            return

        channel = data.get("channel", {})
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return

        alt = alternatives[0]
        transcript = alt.get("transcript", "").strip()
        confidence = alt.get("confidence", 0.0)
        if not transcript:
            return

        # Extract speaker + timing from word-level diarization
        words = alt.get("words", [])
        speaker = words[0].get("speaker", 0) if words else 0
        start_ms = int(words[0].get("start", 0) * 1000) if words else 0
        end_ms = int(words[-1].get("end", 0) * 1000) if words else 0

        await self._on_turn(transcript, confidence, speaker, start_ms, end_ms)


# ── WebSocket handler ─────────────────────────────────────────────────────────

@router.websocket("/ws/human/{call_sid}")
async def human_stream_handler(websocket: WebSocket, call_sid: str) -> None:
    """
    Handle Twilio Media Streams for a human-agent call.
    Transcribes in real-time with Deepgram diarization.
    Runs GPT-4o analysis when the call ends.
    """
    await websocket.accept()
    logger.info("Human stream WebSocket connected: call_sid=%s", call_sid)

    deepgram: _HumanDeepgramClient | None = None
    human_call_id: str | None = None
    transcript_turns: list[dict] = []   # accumulated during call

    async def on_turn(text: str, confidence: float, speaker: int, start_ms: int, end_ms: int) -> None:
        turn = {
            "speaker": speaker,
            "text": text,
            "confidence": confidence,
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        transcript_turns.append(turn)
        logger.debug("Human turn: speaker=%d text=%s", speaker, text[:60])

    try:
        async for raw_message in websocket.iter_text():
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event_type = message.get("event")

            if event_type == "connected":
                logger.debug("Human stream: Twilio connected")

            elif event_type == "start":
                start_data = message.get("start", {})
                custom_params = start_data.get("customParameters", {})
                human_call_id = custom_params.get("humanCallId")
                actual_call_sid = start_data.get("callSid", call_sid)

                logger.info("Human stream start: call_sid=%s human_call_id=%s", actual_call_sid, human_call_id)

                # Mark CallAnalysis as pending/transcribing
                if human_call_id:
                    asyncio.create_task(_create_analysis_record(human_call_id))

                deepgram = _HumanDeepgramClient(on_turn=on_turn)
                await deepgram.connect()

            elif event_type == "media":
                if deepgram is None:
                    continue
                payload = message.get("media", {}).get("payload", "")
                if not payload:
                    continue
                mulaw_bytes = decode_twilio_payload(payload)
                pcm_bytes = mulaw_to_pcm16(mulaw_bytes)
                await deepgram.send_audio(pcm_bytes)

            elif event_type == "stop":
                logger.info("Human stream stop: call_sid=%s turns=%d", call_sid, len(transcript_turns))
                break

    except WebSocketDisconnect:
        logger.info("Human stream WebSocket disconnected: call_sid=%s", call_sid)
    except Exception as exc:
        logger.error("Human stream error for %s: %s", call_sid, exc, exc_info=True)
    finally:
        if deepgram:
            await deepgram.close()
        # Run post-call analysis regardless of how the connection ended
        if human_call_id and transcript_turns:
            asyncio.create_task(
                _run_post_call_analysis(human_call_id, call_sid, transcript_turns)
            )
        elif human_call_id:
            # Call ended but no transcript (too short, silent, etc.)
            asyncio.create_task(_mark_analysis_failed(human_call_id, "No transcript captured"))

        logger.info("Human stream session cleaned up: call_sid=%s", call_sid)


async def _create_analysis_record(human_call_id: str) -> None:
    """Create a pending CallAnalysis row as soon as the call starts."""
    from sqlalchemy import select
    from app.models.database.call_analysis import CallAnalysis
    from app.models.database.human_call import HumanCall

    try:
        async with AsyncSessionLocal() as db:
            hc = await db.get(HumanCall, uuid.UUID(human_call_id))
            if not hc:
                return
            existing = await db.execute(
                select(CallAnalysis).where(CallAnalysis.human_call_id == hc.id)
            )
            if existing.scalar_one_or_none():
                return
            analysis = CallAnalysis(
                human_call_id=hc.id,
                transcription_status="processing",
                analysis_status="pending",
                transcription_started_at=datetime.now(timezone.utc),
            )
            db.add(analysis)
            await db.commit()
    except Exception as exc:
        logger.error("Failed to create analysis record for human call %s: %s", human_call_id, exc)


async def _run_post_call_analysis(
    human_call_id: str,
    call_sid: str,
    turns: list[dict],
) -> None:
    """
    Persist transcript + run GPT-4o analysis after the call ends.
    """
    from sqlalchemy import select
    from app.models.database.call_analysis import CallAnalysis
    from app.models.database.human_call import HumanCall
    from app.agents.call_intelligence.analyzer import CallAnalyzer

    try:
        async with AsyncSessionLocal() as db:
            hc = await db.get(HumanCall, uuid.UUID(human_call_id))
            if not hc:
                logger.error("post_call_analysis: HumanCall %s not found", human_call_id)
                return

            # Update call record
            hc.status = "completed"
            if not hc.ended_at:
                hc.ended_at = datetime.now(timezone.utc)
            if hc.started_at and hc.ended_at:
                hc.duration_seconds = int((hc.ended_at - hc.started_at).total_seconds())

            # Get or create CallAnalysis
            result = await db.execute(
                select(CallAnalysis).where(CallAnalysis.human_call_id == hc.id)
            )
            analysis = result.scalar_one_or_none()
            if not analysis:
                analysis = CallAnalysis(human_call_id=hc.id)
                db.add(analysis)

            # Build readable transcript text
            transcript_text = "\n".join(
                f"[Speaker {t['speaker']}]: {t['text']}" for t in turns
            )

            analysis.transcript_speakers = turns
            analysis.transcript_text = transcript_text
            analysis.transcription_model = "deepgram-nova-2"
            analysis.transcription_status = "completed"
            analysis.transcription_completed_at = datetime.now(timezone.utc)
            analysis.analysis_status = "processing"
            analysis.analysis_started_at = datetime.now(timezone.utc)
            await db.flush()

            # Build context from the call's stored debt info (no borrower DB record needed)
            borrower_context: dict = {}
            if hc.amount_due is not None:
                borrower_context["current_balance"] = float(hc.amount_due)
            if hc.days_overdue is not None:
                borrower_context["days_past_due"] = hc.days_overdue

            analyzer = CallAnalyzer()
            try:
                ai_result = await analyzer.analyze_transcript(transcript_text, borrower_context)
            except Exception as exc:
                analysis.analysis_status = "failed"
                analysis.analysis_error = str(exc)
                await db.commit()
                logger.error("GPT-4o analysis failed for human call %s: %s", human_call_id, exc)
                return

            # Persist intelligence
            analysis.overall_sentiment = ai_result.overall_sentiment
            analysis.sentiment_score = ai_result.sentiment_score
            analysis.willingness_to_pay = ai_result.willingness_to_pay
            analysis.payment_intent_score = ai_result.payment_intent_score
            analysis.key_points = ai_result.key_points
            analysis.borrower_characterization = ai_result.borrower_characterization
            analysis.repayment_probability = ai_result.repayment_probability
            analysis.repayment_probability_reason = ai_result.repayment_probability_reason
            analysis.recommended_strategy = ai_result.recommended_strategy
            analysis.next_call_talking_points = ai_result.next_call_talking_points
            analysis.analysis_model = ai_result.model_used
            analysis.analysis_status = "completed"
            analysis.analysis_completed_at = datetime.now(timezone.utc)

            await db.commit()
            logger.info(
                "Human call analysis complete: id=%s sentiment=%s repayment=%.2f",
                human_call_id, ai_result.overall_sentiment, ai_result.repayment_probability,
            )

    except Exception as exc:
        logger.error("Post-call analysis failed for human call %s: %s", human_call_id, exc, exc_info=True)


async def _mark_analysis_failed(human_call_id: str, reason: str) -> None:
    """Mark analysis as failed when call ends with no transcript."""
    from sqlalchemy import select
    from app.models.database.call_analysis import CallAnalysis
    from app.models.database.human_call import HumanCall

    try:
        async with AsyncSessionLocal() as db:
            hc = await db.get(HumanCall, uuid.UUID(human_call_id))
            if not hc:
                return
            hc.status = "completed"
            if not hc.ended_at:
                hc.ended_at = datetime.now(timezone.utc)

            result = await db.execute(
                select(CallAnalysis).where(CallAnalysis.human_call_id == hc.id)
            )
            analysis = result.scalar_one_or_none()
            if analysis:
                analysis.transcription_status = "failed"
                analysis.analysis_status = "failed"
                analysis.analysis_error = reason
            await db.commit()
    except Exception as exc:
        logger.error("Failed to mark analysis failed for %s: %s", human_call_id, exc)
