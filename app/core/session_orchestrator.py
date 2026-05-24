"""
Session Orchestrator — the central coordinator for a live call.

Manages:
- Call state machine (greeting → mini_miranda → negotiating → closing → ended)
- Turn-taking: receives STT transcripts, generates LLM response, dispatches TTS
- Barge-in interrupt handling
- Real-time compliance guard on every LLM response
- Function call execution (record_promise, opt_out, dispute, etc.)
- Redis session state updates

This is the most latency-sensitive module in the system.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.config import get_settings
from app.core.barge_in_detector import BargeInDetector
from app.core.conversation_manager import ConversationManager
from app.core.turn_detector import TurnDetector
from app.services.compliance.fdcpa_guard import check_agent_response, check_borrower_speech
from app.services.llm.gpt4o_client import GPT4oClient
from app.services.llm.prompt_builder import (
    BorrowerContext, CampaignContext, build_system_prompt
)
from app.services.memory.redis_session import RedisSessionManager
from app.services.memory.vector_store import get_vector_store
from app.services.profiling.sentiment_analyzer import analyze_sentiment, extract_entities
from app.services.tts.factory import create_tts_provider

logger = logging.getLogger(__name__)

CALL_STATES = ["greeting", "mini_miranda", "negotiating", "closing", "ended"]

# ── Refusal detection keywords ─────────────────────────────────────────────────
REFUSAL_KEYWORDS = [
    # Explicit refusals
    "won't pay", "will not pay", "not going to pay", "not paying",
    "refuse to pay", "never paying", "i'm not paying", "im not paying",
    "don't owe", "do not owe", "not my problem", "not my debt",
    "forget it", "leave me alone", "stop bothering", "go away",
    "not interested", "hang up", "i said no", "my answer is no",
    "absolutely not", "no way", "never", "stop calling me",
    # Short denials (common real responses)
    "no money", "don't have money", "i don't have money", "have no money",
    "cannot pay", "can't pay", "not able to pay", "unable to pay",
    "no funds", "not in a position",
    # Bare "no" — match as whole word to avoid false positives
    "no.", "no!", "no,",
    # ── Hindi (हिन्दी) refusals ────────────────────────────────────────────────
    "नहीं",           # No / not (bare)
    "नहीं दूंगा",     # Will not give/pay (masculine)
    "नहीं दूंगी",     # Will not give/pay (feminine)
    "नहीं भरूंगा",    # Will not fill/pay (masculine)
    "नहीं भरूंगी",    # Will not fill/pay (feminine)
    "नहीं है",        # Don't have / not there
    "पैसे नहीं",      # No money
    "पैसे नहीं हैं",  # Don't have money
    "पैसा नहीं",      # No money (singular)
    "पैसा नहीं है",   # Don't have money
    "मेरे पास नहीं",  # I don't have
    "नहीं कर सकता",   # Cannot do (masculine)
    "नहीं कर सकती",   # Cannot do (feminine)
    "नहीं करूंगा",    # Will not do (masculine)
    "नहीं करूंगी",    # Will not do (feminine)
    "मत करो",         # Don't do this
    "बंद करो",        # Stop it
    "छोड़ो",          # Leave it / forget it
    "मुझे नहीं",      # Not for me / I don't want
    "salary नहीं",    # No salary (common mixed Hindi-English)
    # ── Kannada (ಕನ್ನಡ) refusals ──────────────────────────────────────────────
    "ಇಲ್ಲ",           # No / not
    "ಕೊಡಲ್ಲ",         # Will not give
    "ಕಟ್ಟಲ್ಲ",        # Will not pay
    "ಸಾಧ್ಯವಿಲ್ಲ",    # Not possible
    "ಹಣ ಇಲ್ಲ",        # No money
    "ದುಡ್ಡು ಇಲ್ಲ",    # No money
    "ಬೇಡ",            # Don't want
    "ಆಗಲ್ಲ",          # Cannot / won't happen
    # ── Telugu (తెలుగు) refusals ──────────────────────────────────────────────
    "లేదు",           # No / not
    "ఇవ్వను",         # Will not give
    "కట్టను",         # Will not pay
    "వద్దు",          # Don't want / no
    "డబ్బు లేదు",     # No money
    "చేయను",          # Will not do
    "సాధ్యం కాదు",    # Not possible
]

# Bare single-word "no" check (standalone utterance like "No" or "No." "No!")
_BARE_NO_PATTERN = __import__("re").compile(r"^\s*no[.!,]?\s*$", __import__("re").IGNORECASE)

# ── Payment intent keywords (positive signals → de-escalate pressure) ─────────
_PAYMENT_INTENT_RE = __import__("re").compile(
    r"\b(i['']?ll\s+pay|i\s+will\s+pay|i\s+can\s+pay|i\s+want\s+to\s+pay|"
    r"i\s+do\s+want\s+to\s+pay|do\s+want\s+to\s+pay|"
    r"i'?m\s+going\s+to\s+pay|going\s+to\s+pay|ready\s+to\s+pay|"
    r"i\s+will\s+give|i['']?ll\s+give|i\s+can\s+give|will\s+pay|can\s+pay|"
    r"i\s+said\s+i\s+will|i\s+said\s+i['']?ll|yes\s+i\s+will\s+pay|"
    r"pay\s+[\d₹$]|pay\s+(hundred|thousand|lakh|rupee|dollar)|"
    r"bhugtan\s+karunga|pay\s+kar\s+d[uo]nga|de\s+d[uo]nga)\b",
    __import__("re").IGNORECASE,
)

# ── Barge-in classification regexes ───────────────────────────────────────────
import re as _re
# Pure listener cues — never require a response; word-count gate applied separately
_PURE_BACKCHANNEL_RE = _re.compile(
    r"^\s*(ok|okay|yes|yeah|yep|sure|alright|uh[\s-]?huh|mhm|mm+|hmm+|huh|right"
    r"|i see|got it|fine|ok ok|okay okay|yeah yeah|ok fine|hmm okay|right right)\s*[.!,]?\s*$",
    _re.IGNORECASE,
)
# Question words — interruption likely contains a real question
_QUESTION_WORDS_RE = _re.compile(
    r"\b(what|how|why|when|where|who|which|amount|balance|much|many|due|owe)\b",
    _re.IGNORECASE,
)
# Resistance/objection words
_OBJECTION_RE = _re.compile(
    r"\b(no|not|don't|can't|won't|never)\b",
    _re.IGNORECASE,
)
# Soft dispute: borrower questioning the amount/balance (not refusing to pay)
_SOFT_DISPUTE_RE = _re.compile(
    r"\b(wrong amount|wrong balance|different amount|not that much|don't have that balance"
    r"|that'?s not right|that'?s incorrect|incorrect amount|incorrect balance"
    r"|don'?t owe that|don'?t think i owe|shouldn'?t be|wasn'?t me|check again|verify that"
    r"|already paid|have paid|i paid|made a payment|made payments|paid it|paid already)\b",
    _re.IGNORECASE,
)


def _is_question(text: str) -> bool:
    """
    True only if the transcript is grammatically a question:
    - ends with '?' and contains a question word, OR
    - starts with an interrogative word (what/how/why/when/where/who/which)
    Avoids false positives like "I don't know what to do".
    """
    stripped = text.strip()
    if stripped.endswith("?"):
        return bool(_QUESTION_WORDS_RE.search(stripped))
    return bool(_re.match(
        r"^\s*(what|how|why|when|where|who|which)\b",
        stripped, _re.IGNORECASE,
    ))


_COMPLETE_VERB_RE = _re.compile(
    r"\b(paid|owe|have|want|do|did|can|will|am|is|are|need|got)\b",
    _re.IGNORECASE,
)


def _is_complete_utterance(text: str) -> bool:
    """True if transcript appears to be a complete thought (not a trailing fragment like 'The thing is')."""
    stripped = text.strip()
    if stripped.endswith(("?", ".", "!")):
        return True
    if _is_question(stripped):
        return True
    return bool(_COMPLETE_VERB_RE.search(stripped))


# ── Localised phrases ─────────────────────────────────────────────────────────
_GREETING: dict[str, str] = {
    "en": "Hi, is {name} available?",
    "hi": "Namaskar, kya {name} ji hain?",
    "kn": "Namaskara, {name} iddareya?",
    "te": "Namaskaram, {name} garu unnara?",
}

_FOLLOW_UP_GREETING: dict[str, str] = {
    "en": "Hi {name}, {agent} from {agency}.",
    "hi": "Namaskar {name}, main {agent}, {agency} se.",
    "kn": "Namaskara {name}, naanu {agent}, {agency} inda.",
    "te": "Namaskaram {name}, nenu {agent}, {agency} nundi.",
}

_MINI_MIRANDA: dict[str, str] = {
    "en": (
        "Hey {name}, this is {agent} calling from {agency}. "
        "Real quick — I need to let you know this call is about a debt, "
        "I'm reaching out about your {creditor} account. You got a minute?"
    ),
    "hi": (
        "Hey {name}, main {agent} bol raha hoon, {agency} se. "
        "Ek zaroori baat — yeh call ek debt ke baare mein hai, "
        "aur aap jo bhi batayenge woh usi kaam ke liye use hoga. "
        "Main aapke {creditor} account ke baare mein baat karna chahta tha. Kya aapke paas ek minute hai?"
    ),
    "kn": (
        "Namaskara {name}, naanu {agent}, {agency} inda matanaaduttiddeene. "
        "Ondu mukhya vishaya — ee call saldha bagge, "
        "neevu needuva maahitiyanu aa uddeshakkaagi balusabahudu. "
        "Nimma {creditor} khaateyya bagge matanaadabekittu. Neemage ondu nimisha samaya ideya?"
    ),
    "te": (
        "Namaskaram {name}, nenu {agent}, {agency} nundi matladutunnanu. "
        "Okka mukhyamaina vishayam — ee call runam gurinchi, "
        "meeru andhinche samaacharam aa prayojanam kosam upayoginchabadutundi. "
        "Meeru {creditor} account gurinchi matladaniki call chesanu. Meeku okka nimisham time undaa?"
    ),
}

_FOLLOW_UP_MINI_MIRANDA: dict[str, str] = {
    "en": (
        "{name}, this is {agent} from {agency}. "
        
    ),
    "hi": (
        "{name}, main {agent} bol raha hoon, {agency} se. "
        
    ),
    "kn": (
        "{name}, naanu {agent}, {agency} inda. "
        
    ),
    "te": (
        "{name}, nenu {agent}, {agency} nundi. "
        
    ),
}

_YIELD_PHRASES: dict[str, list[str]] = {
    "en": ["Yeah, go ahead.", "Sure.", "Go ahead."],
    "hi": ["Haan, boliye.", "Zaroor.", "Haan kahiye."],
    "kn": ["Haudu, heli.", "Khandita.", "Maatnaadi."],
    "te": ["Avunu, cheppandi.", "Tappakundaa.", "Cheppandi."],
}


class SessionOrchestrator:
    """
    One instance per active call. Owned by the WebSocket media stream handler.

    Lifecycle:
      1. create() — initialize Redis session
      2. on_transcript() — called for every final STT result
      3. close() — cleanup on call end
    """

    def __init__(
        self,
        call_sid: str,
        borrower_ctx: BorrowerContext,
        campaign_ctx: CampaignContext,
        follow_up_context: str,
        follow_up_opening_line: str,
        follow_up_first_turn_instruction: str,
        on_audio_chunk: Callable[[bytes], Any],           # Callback: send mulaw chunk to Twilio WS
        on_call_end: Callable[[str], Any],                # Callback: call ended with outcome
        on_clear_buffer: Callable[[], Awaitable[None]] | None = None,  # Callback: flush Twilio audio buffer
    ) -> None:
        self.call_sid = call_sid
        self._borrower_ctx = borrower_ctx
        self._campaign_ctx = campaign_ctx
        self._follow_up_context = follow_up_context
        self._follow_up_opening_line = follow_up_opening_line
        self._follow_up_first_turn_instruction = follow_up_first_turn_instruction
        self._on_audio_chunk = on_audio_chunk
        self._on_call_end = on_call_end
        self._on_clear_buffer = on_clear_buffer

        settings = get_settings()
        self._agency_name = settings.agency_name
        self._agent_name = settings.agent_name

        self._session = RedisSessionManager(call_sid)
        self._conversation = ConversationManager(self._session)
        self._llm = GPT4oClient()
        self._tts = create_tts_provider(language=self._borrower_ctx.preferred_language)
        self._barge_in = BargeInDetector()
        self._turn_detector = TurnDetector()
        self._vector_store = get_vector_store()

        self._tts_task: Optional[asyncio.Task] = None
        self._generate_task: Optional[asyncio.Task] = None
        self._speech_id: int = 0   # monotonic counter — each utterance captures its own ID; interrupt increments it
        self._call_start_ms: int = int(time.monotonic() * 1000)
        self._turn_latencies_llm: list[int] = []
        self._turn_latencies_tts: list[int] = []

        # ── Barge-in state ────────────────────────────────────────────────────
        self._barge_in_note: str | None = None         # context note injected into LLM on real barge-in
        self._barge_in_intent: str | None = None       # "question" | "objection" | "clarification"
        self._payment_intent_note: str | None = None   # injected when borrower signals willingness to pay
        self._last_agent_utterance: str | None = None  # last sentence spoken, for barge-in context
        self._last_barge_in_ts: float = 0.0            # cooldown: time.monotonic() of last real barge-in
        self._interruptible: bool = True                # False during mini_miranda / compliance speech
        self._last_processed_transcript: str = ""      # dedup: normalized form of last accepted transcript
        self._pending_question: bool = False            # True when this turn is a direct question
        self._is_yielding: bool = False                 # True while yield phrase audio is playing
        self._post_barge_in_debounce_until: float = 0.0  # suppress short fragments after barge-in
        self._barge_in_pending: bool = False            # True when early interrupt fired on interim
        self._gen_id: int = 0                           # incremented on interrupt; guards stale LLM results
        self._last_yield_ts: float = 0.0                # prevents multiple yield phrases within 1.5s
        self._follow_up_first_turn_pending: bool = bool(follow_up_first_turn_instruction.strip())
        self._follow_up_mode: bool = bool(follow_up_context.strip())
        self._follow_up_opening_delivered: bool = False

    async def initialize(self, strategy: str) -> None:
        """Create Redis session and deliver the opening agent greeting."""
        await self._session.create(
            borrower_id=str(self._borrower_ctx.borrower_id),
            strategy=strategy,
        )
        # Deliver opening greeting immediately (localised)
        lang = self._borrower_ctx.preferred_language
        greeting_template = (
            _FOLLOW_UP_GREETING.get(lang, _FOLLOW_UP_GREETING["en"])
            if self._follow_up_mode
            else _GREETING.get(lang, _GREETING["en"])
        )
        greeting = greeting_template.format(
            name=self._borrower_ctx.first_name,
            agent=self._agent_name,
            agency=self._agency_name,
        )
        await self._speak(greeting, is_opening=True)

    def _detect_refusal(self, transcript: str) -> bool:
        """Return True if transcript contains a clear refusal to pay."""
        lower = transcript.lower().strip()
        if _BARE_NO_PATTERN.match(lower):
            return True
        return any(kw in lower for kw in REFUSAL_KEYWORDS)

    def _detect_soft_dispute(self, transcript: str) -> bool:
        """Return True if borrower is questioning the amount/balance, not refusing to pay."""
        return bool(_SOFT_DISPUTE_RE.search(transcript))

    def _detect_payment_intent(self, transcript: str) -> bool:
        """Return True if borrower is signalling willingness to pay."""
        return bool(_PAYMENT_INTENT_RE.search(transcript))

    def mark_audio_barge_in(self) -> None:
        """
        Called by media_stream audio-level detector when speech energy interrupts playback.
        Sets _barge_in_pending so the next on_transcript() processes it as a barge-in
        (plays yield phrase + starts LLM) rather than as a plain normal turn.
        Does NOT play yield here — that's done by on_transcript() once we know what was said.
        """
        self._barge_in_pending = True
        self._last_barge_in_ts = time.monotonic()

    async def on_transcript(self, transcript: str, confidence: float, is_final: bool) -> None:
        """
        Called by DeepgramStreamingClient for every incoming transcript.
        For final transcripts: runs compliance check, LLM inference, TTS dispatch.
        For interim: ignored (barge-in detection handled at infrastructure level).
        """
        # ── 1. Interim fast-path: AUDIO INTERRUPT ONLY — never start LLM from interim ──
        # Interim transcripts are used ONLY to stop audio early.
        # _generate_and_speak is NEVER called here — always triggered by the final transcript.
        if not is_final:
            # Skip duplicate interims (Deepgram may resend unchanged)
            if self._barge_in.is_duplicate_interim(transcript):
                return
            # Feed interim to turn detector for speech velocity tracking
            self._turn_detector.feed_interim(transcript)
            if (
                transcript
                and not self._is_yielding
                and self._interruptible
                and not _PURE_BACKCHANNEL_RE.match(transcript)
                # Require substantive content: ≥3 words AND (verb/question word OR ≥5 words).
                # Blocks "I", "I think", "I think I" (all stopwords) while passing
                # "What is my balance" (question word), "I want to stop" (verb), etc.
                and len(transcript.split()) >= 3
                and (
                    _COMPLETE_VERB_RE.search(transcript)
                    or _QUESTION_WORDS_RE.search(transcript)
                    or len(transcript.split()) >= 5
                )
            ):
                if await self._session.is_agent_speaking():
                    now = time.monotonic()
                    if now - self._last_barge_in_ts >= 0.4:
                        await self._interrupt_tts()
                        self._barge_in_pending = True   # final will complete the barge-in flow
                        self._last_barge_in_ts = now    # set here so final skips cooldown correctly
                        from app.monitoring.metrics import barge_in_triggered
                        barge_in_triggered.labels(path="interim_transcript").inc()
                        logger.debug("Early barge-in interrupt on interim: '%s'", transcript[:40])
            return   # always return — never process interim beyond interrupt

        transcript = transcript.strip()
        if not transcript:
            return

        # Reset interim dedup tracker on every final transcript
        self._barge_in.reset_interim_dedup()

        # ── 2. Duplicate suppression ─────────────────────────────────────────
        normalized = transcript.lower().rstrip(".!,")
        # Skip duplicate check when a barge-in was already committed on the interim.
        # The final is a brand-new utterance from the borrower's perspective — dropping it
        # would leave the system silent even though a valid response was expected.
        if not self._barge_in_pending and normalized == self._last_processed_transcript:
            logger.debug("Duplicate transcript ignored: '%s'", transcript)
            return
        self._last_processed_transcript = normalized

        # ── 3. STT confidence filter ──────────────────────────────────────────
        if confidence < 0.6:
            logger.debug("STT confidence %.2f below threshold, ignoring", confidence)
            return

        # ── 4. Minimum length (< 2 chars = pure noise/breath) ─────────────────
        if len(transcript) < 2:
            logger.debug("Transcript too short ('%s'), ignoring", transcript)
            return

        words = transcript.split()

        # ── 6. Barge-in handling ──────────────────────────────────────────────
        _was_barge_in_pending = self._barge_in_pending
        self._barge_in_pending = False

        if (await self._session.is_agent_speaking()) or _was_barge_in_pending:
            try:
                if not self._interruptible:
                    return

                if len(words) <= 3 and normalized != "no" and _PURE_BACKCHANNEL_RE.match(transcript):
                    return

                # Skip cooldown if we already interrupted on interim (ts was set then)
                if not _was_barge_in_pending:
                    now = time.monotonic()
                    if now - self._last_barge_in_ts < 0.4:
                        return
                    self._last_barge_in_ts = now

                # Semantic completeness (replaces word-count soft/hard)
                is_complete = _is_complete_utterance(transcript)

                # Classify intent
                if _is_question(transcript):
                    intent = "question"
                    intent_hint = "This is a question — answer directly."
                elif _OBJECTION_RE.search(transcript):
                    intent = "objection"
                    intent_hint = "This is resistance — respond with persuasion."
                else:
                    intent = "clarification"
                    intent_hint = "This is likely clarification — respond briefly."

                # ── Special case: final arrived while yield is currently playing ──
                # Do NOT interrupt the yield or call _speak_yield() again.
                # For complete utterances, start the LLM now — _stream_tts_from_queue
                # already waits on `while self._is_yielding` so audio won't overlap.
                if self._is_yielding:
                    if intent == "question" or is_complete:
                        prev = f" You were saying: '{(self._last_agent_utterance or '')[:80]}'."
                        self._barge_in_note = (
                            f"You were speaking and got interrupted: '{transcript[:100]}'.{prev} "
                            f"Prefer continuing your previous sentence unless the interruption requires a full answer. "
                            f"{intent_hint}"
                        )
                        self._barge_in_intent = intent
                        if self._generate_task and not self._generate_task.done():
                            self._generate_task.cancel()
                        self._gen_id += 1
                        self._generate_task = asyncio.create_task(self._generate_and_speak(transcript))
                        self._post_barge_in_debounce_until = time.monotonic() + 1.0
                        logger.info("BARGE-IN (during yield) | text='%s' | intent=%s — LLM queued", transcript[:60], intent)
                    return  # never re-trigger yield while one is playing

                # Only interrupt TTS if not already done on interim
                if not _was_barge_in_pending:
                    await self._interrupt_tts()

                prev = f" You were saying: '{(self._last_agent_utterance or '')[:80]}'."
                self._barge_in_note = (
                    f"You were speaking and got interrupted: '{transcript[:100]}'.{prev} "
                    f"Prefer continuing your previous sentence unless the interruption requires a full answer. "
                    f"{intent_hint}"
                )
                self._barge_in_intent = intent
                logger.info("BARGE-IN | text='%s' | complete=%s | intent=%s", transcript, is_complete, intent)

                # Payment intent check on barge-in transcripts — normal path returns early
                # so this check would otherwise be skipped entirely.
                if self._detect_payment_intent(transcript) and self._borrower_ctx.pressure_level > 0:
                    logger.info("💚 Payment intent in barge-in: '%s' — de-escalating from level %d", transcript[:60], self._borrower_ctx.pressure_level)
                    self._borrower_ctx.pressure_level = 0
                    await self._session.set("refusal_count", "0")
                    self._payment_intent_note = (
                        f"BORROWER SIGNALED PAYMENT INTENT (while interrupting): '{transcript[:100]}'. "
                        f"De-escalate immediately. Acknowledge positively. Ask for a specific amount and date. "
                        f"Then call record_promise(). One warm sentence. No pressure."
                    )

                # For complete utterances: start LLM NOW using the FINAL transcript.
                # _stream_tts_from_queue waits for _is_yielding=False before playing audio,
                # so the answer is ready the moment the yield phrase finishes.
                if intent == "question" or is_complete:
                    if self._generate_task and not self._generate_task.done():
                        self._generate_task.cancel()
                    self._gen_id += 1   # commit: this generation supersedes all previous
                    self._generate_task = asyncio.create_task(self._generate_and_speak(transcript))

                # Yield cooldown: suppress "Sure... Sure..." from rapid consecutive barge-ins.
                # Skipping yield does NOT skip LLM — generation already fired above.
                _now = time.monotonic()
                if _now - self._last_yield_ts >= 1.5:
                    self._last_yield_ts = _now
                    await self._speak_yield()
                self._post_barge_in_debounce_until = time.monotonic() + 1.0
                return

            except Exception as _exc:
                logger.warning("Barge-in logic error, hard interrupt fallback: %s", _exc)
                await self._interrupt_tts()

        # ── Compliance: scan borrower speech for opt-out / dispute ────────────
        compliance_actions = check_borrower_speech(transcript)
        for action in compliance_actions:
            if action.action_type == "opt_out":
                await self._handle_opt_out(action.trigger)
                return
            elif action.action_type == "dispute":
                await self._handle_dispute(transcript)
                return

        # ── Analyze sentiment + extract entities ─────────────────────────────
        sentiment = analyze_sentiment(transcript)
        entities = extract_entities(transcript)

        # ── Update Redis session ──────────────────────────────────────────────
        await self._session.increment_turn()
        await self._conversation.add_borrower_turn(
            text=transcript,
            confidence=confidence,
            sentiment=sentiment.score,
            entities=entities,
        )

        # Update session entities
        existing = await self._session.get("entities_extracted")
        import json
        try:
            existing_dict = json.loads(existing or "{}")
        except Exception:
            existing_dict = {}
        for k, v in entities.items():
            if isinstance(v, list):
                existing_dict.setdefault(k, [])
                existing_dict[k].extend(v)
        await self._session.set("entities_extracted", existing_dict)

        # ── State: ensure mini miranda is delivered first ─────────────────────
        state = await self._session.get_state()
        if state == "mini_miranda":
            await self._deliver_mini_miranda_response(transcript)
            return

        # ── Soft dispute: balance disagreement → clarification mode, not pressure ──
        if self._detect_soft_dispute(transcript):
            self._pending_question = True   # reuse question-first bypass: no pressure this turn
            logger.info("Soft dispute detected — routing to clarification mode: '%s'", transcript[:60])
            if self._generate_task and not self._generate_task.done():
                self._generate_task.cancel()
            self._gen_id += 1
            self._generate_task = asyncio.create_task(self._generate_and_speak(transcript))
            return

        # ── Detect payment intent — de-escalate pressure immediately ─────────
        if self._detect_payment_intent(transcript) and self._borrower_ctx.pressure_level > 0:
            logger.info("💚 Payment intent detected in: '%s' — de-escalating from level %d", transcript[:60], self._borrower_ctx.pressure_level)
            self._borrower_ctx.pressure_level = 0
            await self._session.set("refusal_count", "0")
            self._payment_intent_note = (
                f"BORROWER SIGNALED PAYMENT INTENT: '{transcript[:100]}'. "
                f"De-escalate immediately. DO NOT mention credit bureaus, legal threats, or consequences. "
                f"Acknowledge positively and warmly ('That's great to hear', 'Good'). "
                f"If they stated an amount (e.g. '100 rupees'), acknowledge it and ask for a specific payment date. "
                f"Then call record_promise() with the amount and date. "
                f"One warm, direct sentence. No pressure."
            )

        # ── Track refusals and escalate pressure level ────────────────────────
        elif self._detect_refusal(transcript):
            count_str = await self._session.get("refusal_count") or "0"
            new_count = int(count_str) + 1
            await self._session.set("refusal_count", str(new_count))
            new_level = min(new_count, 4)
            self._borrower_ctx.pressure_level = new_level
            logger.warning("🔴 REFUSAL #%d detected in: '%s' — pressure_level=%d", new_count, transcript[:60], new_level)
            # Append escalation event to pressure_log for post-call persistence
            import json as _json
            event = _json.dumps({
                "level": new_level,
                "trigger": transcript[:120],
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            await self._session._r.rpush(f"session:{self._session.call_sid}:pressure_log", event)
        else:
            logger.info("✅ No refusal detected (level=%d) in: '%s'", self._borrower_ctx.pressure_level, transcript[:60])

        # ── Post-barge-in debounce: drop short fragments while borrower is still speaking ──
        # After a barge-in, borrower often continues mid-sentence after the yield phrase.
        # Responding to "The thing is," before they finish creates a jarring double-interrupt.
        # Window: 1s (down from 2s — Deepgram utterance_end_ms is ~1s, so 2s was too aggressive)
        # Threshold: 4 words (down from 6 — "OK sure I'll pay" is 4 words and legitimate)
        if (
            time.monotonic() < self._post_barge_in_debounce_until
            and len(words) < 4
            and not transcript.strip().endswith((".", "?", "!"))
            and not _COMPLETE_VERB_RE.search(transcript)
        ):
            logger.debug("Post-barge-in debounce: ignoring fragment '%s'", transcript[:40])
            return

        # ── Turn completion detection ─────────────────────────────────────────
        # Predict whether the borrower is done speaking using linguistic analysis.
        # Prevents "I want to pay... [pause] ...but I can't afford the full amount"
        # from being split into two turns. Waits up to 1.5s for continuation.
        turn = self._turn_detector.analyze(transcript, confidence)

        # Instrument every decision for offline analysis
        from app.monitoring.metrics import turn_decisions
        _decision = "complete" if turn.is_complete else "incomplete"
        turn_decisions.labels(decision=_decision, reason=turn.reason).inc()

        if not turn.is_complete and turn.confidence > 0.7:
            # High confidence the borrower will continue — wait for next final
            logger.info("TURN_WAIT | conf=%.2f | reason=%s | text='%s'", turn.confidence, turn.reason, transcript[:50])
            self._turn_detector.reset()
            return
        self._turn_detector.reset()

        # ── Question-first: applies to ALL transcripts, not only barge-ins ──────
        # Structural flag — prevents pressure injection in _generate_and_speak for this turn
        self._pending_question = _is_question(transcript)

        # ── Generate LLM response — fire-and-forget so receive_loop stays unblocked ─
        # Blocking here (await) would prevent Deepgram from delivering new transcripts
        # until the full LLM+TTS pipeline finishes (~4-8s), making barge-in impossible.
        if self._generate_task and not self._generate_task.done():
            self._generate_task.cancel()
        self._gen_id += 1
        self._generate_task = asyncio.create_task(self._generate_and_speak(transcript))

    async def _generate_and_speak(self, borrower_text: str) -> None:
        """Full STT → LLM → TTS pipeline for a single turn."""
        my_gen_id = self._gen_id   # capture at start to detect stale results

        # Retrieve semantic context from past conversations
        retrieved_context = await self._vector_store.retrieve_context(
            borrower_id=str(self._borrower_ctx.borrower_id),
            query=borrower_text,
        )

        system_prompt = build_system_prompt(
            borrower=self._borrower_ctx,
            campaign=self._campaign_ctx,
            retrieved_context=retrieved_context,
            follow_up_context=self._follow_up_context,
            agency_name=self._agency_name,
            agent_name=self._agent_name,
        )
        messages = await self._conversation.get_gpt_messages()

        # Atomically consume turn-level overrides — prevents stale state if a second
        # barge-in fires between read and clear of these fields
        barge_in_note = self._barge_in_note
        barge_in_intent = self._barge_in_intent
        pending_question = self._pending_question
        payment_intent_note = self._payment_intent_note
        self._barge_in_note = None
        self._barge_in_intent = None
        self._pending_question = False
        self._payment_intent_note = None

        # Inject language reminder as final user message so it's top-of-mind for GPT-4o
        from app.services.llm.prompt_builder import LANGUAGE_REMINDER, PRESSURE_INSTRUCTIONS
        lang = self._borrower_ctx.preferred_language
        reminder = LANGUAGE_REMINDER.get(lang)
        if reminder:
            messages = messages + [{"role": "user", "content": reminder}]
        if self._follow_up_first_turn_pending:
            messages = messages + [{"role": "user", "content": self._follow_up_first_turn_instruction}]
            self._follow_up_first_turn_pending = False

        # Question-first bypass — structurally skip pressure when borrower asked a question
        is_question_turn = pending_question or barge_in_intent == "question"

        level = self._borrower_ctx.pressure_level
        if not is_question_turn and level > 0:
            # Normal pressure injection — only when NOT answering a question.
            # ONE-SHOT: fire the pressure script ONCE then reset to 0.
            # refusal_count in Redis is untouched — next refusal escalates to the right level.
            pressure_text = PRESSURE_INSTRUCTIONS.get(level, PRESSURE_INSTRUCTIONS[4])
            pressure_reminder = (
                f"[SYSTEM ALERT — PRESSURE LEVEL {level} ACTIVE]\n"
                f"Borrower has refused {level} time(s). Do NOT ask 'by when can you pay'. "
                f"Follow this instruction RIGHT NOW: {pressure_text}"
            )
            messages = messages + [{"role": "user", "content": pressure_reminder}]
            # Discharge: reset so the same threat isn't repeated on every subsequent turn.
            # A new refusal will set pressure_level again via on_transcript().
            self._borrower_ctx.pressure_level = 0

        # Payment intent override — highest priority, overrides everything else
        if payment_intent_note:
            messages = messages + [{"role": "user", "content": payment_intent_note}]
        # Inject barge-in context or question-turn instruction
        elif is_question_turn:
            context = barge_in_note or f"The borrower asked: '{borrower_text}'"
            messages = messages + [{"role": "user", "content": (
                f"[ANSWER THE QUESTION FIRST — STRICT FORMAT]\n{context}\n\n"
                f"RESPONSE FORMAT — MANDATORY:\n"
                f"• Sentence 1: Answer ONLY the specific question using exact account data. "
                f"No consequences, no credit report, no urgency — just the answer.\n"
                f"• Sentence 2 (optional): One brief follow-up DIRECTLY related to their question.\n\n"
                f"HARD RULE: Do NOT mention credit reports, legal consequences, or pressure in either sentence. "
                f"Violating this rule is a compliance failure."
            )}]
        elif barge_in_note:
            messages = messages + [{"role": "user", "content": barge_in_note}]

        t_llm_start = time.monotonic()
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        _fast_sentence_used = False

        async def on_sentence(sentence: str) -> None:
            nonlocal _fast_sentence_used
            # If fast model already delivered the first sentence, skip the main model's
            # first sentence to avoid duplication (they'll be similar but not identical)
            if _fast_sentence_used and sentence_queue.qsize() == 0:
                _fast_sentence_used = False  # only skip once
                return
            await sentence_queue.put(sentence)

        # Guard: discard stale LLM result if a new barge-in fired while LLM was running
        if my_gen_id != self._gen_id:
            await sentence_queue.put(None)
            return

        # Start TTS dispatch task (runs concurrently with LLM streaming)
        self._tts_task = asyncio.create_task(
            self._stream_tts_from_queue(sentence_queue)
        )

        # ── Fast-first-sentence: race a small model for lower TTFT ────────────
        # Fire gpt-4o-mini for just the first sentence (~100-200ms TTFT) while
        # the main gpt-4o streams the full response (~400-600ms TTFT).
        # Whichever produces a first sentence first wins.
        #
        # SKIP the fast path when:
        # - Question turns (need precise data from full context)
        # - Pressure/compliance turns (mini is less reliable on FDCPA constraints)
        # - Payment intent turns (need careful de-escalation phrasing)
        # - First turn of call (greeting + mini-Miranda — compliance-critical)
        _compliance_sensitive = (
            is_question_turn
            or payment_intent_note is not None
            or (level > 0 and not is_question_turn)  # pressure turn
            or barge_in_note is not None  # barge-in needs context-aware response
        )
        from app.monitoring.metrics import fast_first_skipped, fast_first_wins, fast_first_ttft
        if not _compliance_sensitive:
            fast_task = asyncio.create_task(
                self._llm.generate_fast_first_sentence(system_prompt, messages)
            )
        else:
            fast_task = None
            _skip_reason = (
                "question" if is_question_turn
                else "payment_intent" if payment_intent_note
                else "pressure" if level > 0
                else "barge_in" if barge_in_note
                else "compliance"
            )
            fast_first_skipped.labels(reason=_skip_reason).inc()

        # Run main LLM (streaming) concurrently
        main_task = asyncio.create_task(
            self._llm.generate_response(
                system_prompt=system_prompt,
                conversation_history=messages,
                on_sentence=on_sentence,
            )
        )

        # If fast model finishes first and main model hasn't sent anything yet,
        # push the fast sentence to TTS immediately
        if fast_task is not None:
            try:
                fast_sentence = await asyncio.wait_for(fast_task, timeout=0.8)
                _fast_ms = int((time.monotonic() - t_llm_start) * 1000)
                fast_first_ttft.observe(_fast_ms)
                if fast_sentence and sentence_queue.empty() and my_gen_id == self._gen_id:
                    await sentence_queue.put(fast_sentence)
                    _fast_sentence_used = True
                    fast_first_wins.inc()
                    logger.info("⚡ Fast first sentence delivered in %dms", _fast_ms)
            except (asyncio.TimeoutError, Exception):
                pass  # fast model too slow or failed — main model will deliver

        # Wait for main LLM to finish
        try:
            llm_result = await main_task
        except asyncio.CancelledError:
            await sentence_queue.put(None)
            raise
        except Exception as llm_exc:
            logger.error("🔴 LLM FAILED (model=%s): %s", self._llm._model, llm_exc, exc_info=True)
            await sentence_queue.put(None)
            await self._tts_task
            return
        await sentence_queue.put(None)   # Signal TTS dispatch to finish

        self._turn_latencies_llm.append(llm_result.latency_ms)
        logger.info(
            "🧠 LLM result: %dms | finish=%s | fn=%s | text=%r",
            llm_result.latency_ms,
            llm_result.finish_reason,
            llm_result.function_name,
            llm_result.text[:120],
        )
        if not llm_result.text and not llm_result.function_name:
            logger.warning("⚠️ LLM returned empty text AND no function call — model gave no response")

        # Wait for TTS to finish
        await self._tts_task

        # ── Handle function calls ─────────────────────────────────────────────
        if llm_result.function_name:
            await self._execute_function(llm_result.function_name, llm_result.function_args)

        # ── Update conversation history ───────────────────────────────────────
        if llm_result.text:
            await self._conversation.add_agent_turn(llm_result.text)

    async def _stream_tts_from_queue(self, queue: asyncio.Queue) -> None:
        """Consume sentences from queue and stream audio to Twilio as they arrive."""
        # Wait for yield phrase to finish — LLM may have started before yield completed
        # so the queue may already have data, but we must not play audio over the yield.
        # Hard timeout: if _is_yielding is somehow stuck (e.g. CancelledError in finally),
        # we must not starve TTS indefinitely — force-proceed after 2 seconds.
        _yield_wait_deadline = time.monotonic() + 2.0
        while self._is_yielding:
            if time.monotonic() > _yield_wait_deadline:
                logger.warning("_is_yielding stuck >2s — forcing reset to unblock TTS")
                self._is_yielding = False
                break
            await asyncio.sleep(0.05)

        self._speech_id += 1          # claim a new speech slot
        my_id = self._speech_id       # capture; any later interrupt increments _speech_id above this
        await self._session.set_agent_speaking(True)
        self._barge_in.agent_started_speaking()
        t_tts_start = time.monotonic()
        total_audio_bytes = 0   # track to estimate Twilio playback duration

        try:
            while True:
                if my_id != self._speech_id:
                    break

                sentence = await queue.get()
                if sentence is None:
                    break

                # Compliance guard before TTS
                guard = check_agent_response(sentence)
                if guard.blocked:
                    logger.warning("TTS blocked by FDCPA guard: %s", guard.reason)
                    continue

                self._last_agent_utterance = sentence  # track for barge-in context note
                async for chunk in self._tts.synthesize_stream(sentence):
                    if my_id != self._speech_id:
                        return  # Hard stop — ID changed, newer speech or interrupt took over
                    total_audio_bytes += len(chunk)
                    await self._on_audio_chunk(chunk)

        finally:
            # Normal completion only: keep agent_speaking=True until Twilio finishes playing.
            # ElevenLabs streams faster than real-time, so we finish sending 1-3s before
            # playback ends. Without this sleep, is_agent_speaking() returns False while
            # Twilio is still playing, making barge-in detection impossible.
            # mulaw 8kHz = 8000 bytes/second.
            # Interrupted path: speech_id changed, Twilio buffer was cleared — no wait needed.
            if my_id == self._speech_id and total_audio_bytes > 0:
                elapsed = time.monotonic() - t_tts_start
                remaining = max(0.0, total_audio_bytes / 8000 - elapsed) + 0.15
                if remaining > 0.05:
                    await asyncio.sleep(remaining)
            await self._session.set_agent_speaking(False)
            self._barge_in.agent_stopped_speaking()
            tts_latency = int((time.monotonic() - t_tts_start) * 1000)
            self._turn_latencies_tts.append(tts_latency)

    async def _speak(self, text: str, is_opening: bool = False) -> None:
        """Synthesize and stream a single text utterance."""
        guard = check_agent_response(text)
        if guard.blocked:
            logger.warning("Opening speech blocked by FDCPA guard: %s", guard.reason)
            return

        self._last_agent_utterance = text   # track for barge-in context note
        self._speech_id += 1
        my_id = self._speech_id
        total_audio_bytes = 0
        await self._session.set_agent_speaking(True)
        self._barge_in.agent_started_speaking()
        t_speak_start = time.monotonic()
        try:
            async for chunk in self._tts.synthesize_stream(text):
                if my_id != self._speech_id:
                    return  # Hard stop — interrupt or newer speech started
                total_audio_bytes += len(chunk)
                await self._on_audio_chunk(chunk)
            await self._conversation.add_agent_turn(text)
        finally:
            if my_id == self._speech_id and total_audio_bytes > 0:
                elapsed = time.monotonic() - t_speak_start
                remaining = max(0.0, total_audio_bytes / 8000 - elapsed) + 0.15
                if remaining > 0.05:
                    await asyncio.sleep(remaining)
            await self._session.set_agent_speaking(False)
            self._barge_in.agent_stopped_speaking()

        # Deliver mini miranda immediately after greeting is spoken
        if is_opening:
            await self._session.set_state("mini_miranda")

    async def _deliver_mini_miranda_response(self, borrower_speech: str) -> None:
        """Deliver required FDCPA mini-miranda disclosure on first real contact."""
        if await self._session.is_mini_miranda_delivered():
            await self._session.set_state("negotiating")
            await self._generate_and_speak(borrower_speech)
            return

        # Confirm identity + deliver mini miranda in one turn (localised)
        lang = self._borrower_ctx.preferred_language
        mini_miranda_template = (
            _FOLLOW_UP_MINI_MIRANDA.get(lang, _FOLLOW_UP_MINI_MIRANDA["en"])
            if self._follow_up_mode
            else _MINI_MIRANDA.get(lang, _MINI_MIRANDA["en"])
        )
        mini_miranda = mini_miranda_template.format(
            name=self._borrower_ctx.first_name,
            agent=self._agent_name,
            agency=self._agency_name,
            creditor=self._borrower_ctx.original_creditor,
        )
        self._interruptible = False   # FDCPA disclosure must never be cut short
        try:
            await self._speak(mini_miranda)
        finally:
            self._interruptible = True
        await self._session.mark_mini_miranda_delivered()
        await self._session.set_state("negotiating")
        if self._follow_up_mode and self._follow_up_opening_line and not self._follow_up_opening_delivered:
            self._follow_up_opening_delivered = True
            self._follow_up_first_turn_pending = False
            await self._speak(self._follow_up_opening_line)

    async def _interrupt_tts(self) -> None:
        """Stop current TTS+LLM pipeline and flush Twilio's audio buffer."""
        # 1. Cancel LLM+TTS pipeline tasks FIRST — prevents new chunks from being
        #    enqueued while we're clearing the buffer.
        if self._generate_task and not self._generate_task.done():
            self._generate_task.cancel()
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
        # 2. Mark agent as not speaking in Redis + local state BEFORE buffer clear
        #    so no new barge-in detection fires during the clear await.
        self._barge_in.agent_stopped_speaking()
        await self._session.set_agent_speaking(False)
        # 3. Send Twilio buffer clear to stop playback on the borrower's end.
        if self._on_clear_buffer:
            await self._on_clear_buffer()
        # 4. LAST: increment speech ID — all chunk-send loops exit on next check.
        #    Done after buffer clear completes so no new TTS task can start sending
        #    with the new ID while Twilio still has stale audio queued.
        self._speech_id += 1
        logger.debug("TTS interrupted by barge-in")

    async def _speak_yield(self) -> None:
        """Brief floor-yield phrase after barge-in — sounds human, not abrupt."""
        import random
        lang = self._borrower_ctx.preferred_language
        phrase = random.choice(_YIELD_PHRASES.get(lang, _YIELD_PHRASES["en"]))
        guard = check_agent_response(phrase)
        if guard.blocked:
            return
        self._speech_id += 1
        my_id = self._speech_id
        self._is_yielding = True   # block new barge-ins while yield phrase plays
        total_audio_bytes = 0
        t_start = time.monotonic()
        await self._session.set_agent_speaking(True)
        self._barge_in.agent_started_speaking()
        try:
            async for chunk in self._tts.synthesize_stream(phrase):
                if my_id != self._speech_id:
                    return  # Hard stop — interrupted again
                total_audio_bytes += len(chunk)
                await self._on_audio_chunk(chunk)
        except Exception:
            pass
        finally:
            # _is_yielding MUST be reset first — before any await.
            # If this coroutine is cancelled during the subsequent sleep/Redis call,
            # the assignment would be skipped if placed after an await, leaving
            # _is_yielding=True permanently and starving _stream_tts_from_queue.
            self._is_yielding = False
            # Wait out remaining Twilio playback lag so no new barge-in fires
            # before the borrower actually hears the end of the yield phrase.
            if my_id == self._speech_id and total_audio_bytes > 0:
                elapsed = time.monotonic() - t_start
                remaining = max(0.0, total_audio_bytes / 8000 - elapsed) + 0.15
                if remaining > 0.05:
                    await asyncio.sleep(remaining)
            await self._session.set_agent_speaking(False)
            self._barge_in.agent_stopped_speaking()

    async def _execute_function(self, name: str, args: dict) -> None:
        """Handle GPT function calls — these are the structured agent actions."""
        logger.info("Executing function: %s args=%s", name, args)

        if name == "end_call":
            outcome = args.get("outcome", "no_outcome")
            await self._session.set_state("ended")
            await self._on_call_end(outcome)

        elif name == "trigger_opt_out":
            await self._handle_opt_out(args.get("reason", "borrower_requested"))

        elif name == "log_dispute":
            await self._handle_dispute(args.get("dispute_reason", "unspecified"))

        elif name == "record_promise":
            # Store promise details in session for post-call persistence
            import json
            await self._session.set("current_offer", args)
            logger.info("Promise recorded: amount=%s date=%s", args.get("amount"), args.get("payment_date"))

        elif name == "escalate_to_human":
            await self._speak("I'm going to transfer you to one of our senior agents right now. Please hold.")
            await self._on_call_end("escalated")

        elif name == "request_callback":
            await self._speak(f"Absolutely. I've noted your callback preference. We'll reach out at the time you requested.")

    async def _handle_opt_out(self, trigger: str) -> None:
        await self._speak("I understand. I'll make a note of that and we will not contact you again.")
        await self._session.set("compliance_flags", ["opt_out_requested"])
        await self._on_call_end("opted_out")

    async def _handle_dispute(self, text: str) -> None:
        await self._speak(
            "I understand you're disputing this debt. I'll note that and we'll pause all activity on your account "
            "while we review. You should receive written verification within 30 days."
        )
        await self._session.set("compliance_flags", ["dispute_raised"])
        await self._on_call_end("dispute_filed")

    def get_average_latencies(self) -> dict:
        return {
            "llm_latency_avg_ms": int(sum(self._turn_latencies_llm) / len(self._turn_latencies_llm)) if self._turn_latencies_llm else None,
            "tts_latency_avg_ms": int(sum(self._turn_latencies_tts) / len(self._turn_latencies_tts)) if self._turn_latencies_tts else None,
        }

    async def close(self) -> None:
        await self._interrupt_tts()
        await self._session.set_state("ended")
