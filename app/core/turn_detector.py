"""
Semantic turn-completion detector.

Replaces fixed silence-duration endpointing with linguistic analysis
that predicts whether the borrower is done speaking.

Handles the critical case:
  "I want to pay... [200ms pause] ...but I can't afford the full amount"
  → Fixed endpointing fires mid-thought. Turn detector waits.

Uses a combination of:
1. Syntactic completeness (sentence structure analysis)
2. Semantic continuation signals (conjunctions, trailing prepositions)
3. Prosody proxy (final word stress patterns from STT confidence)
4. Transcript evolution velocity (are new words still arriving?)

This runs on every final transcript BEFORE the LLM is invoked.
"""
from __future__ import annotations

import re
import time
from collections import deque

# ── Continuation signals ─────────────────────────────────────────────────────
# Words/patterns that strongly predict the speaker will continue

# Trailing conjunctions — almost always mean more is coming
_TRAILING_CONJUNCTION = re.compile(
    r"\b(but|and|or|so|because|since|although|though|however|"
    r"also|plus|except|unless|if|when|while|that|which|who|"
    r"lekin|aur|ya|kyunki|par|magar)\s*[,.]?\s*$",
    re.IGNORECASE,
)

# Trailing prepositions — incomplete thought
_TRAILING_PREPOSITION = re.compile(
    r"\b(to|for|with|about|from|in|on|at|of|by|into|like|"
    r"ke\s+liye|ke\s+baare|se|mein|par|ko)\s*$",
    re.IGNORECASE,
)

# Incomplete verb phrases — "I was going to", "I have been"
_INCOMPLETE_VERB = re.compile(
    r"\b(going to|want to|need to|have to|trying to|able to|supposed to|"
    r"was going|were going|am going|will be|would be|could be|"
    r"I was|I am|I have been|I think|I feel|I mean|the thing is|"
    r"karna chahta|karne wala|sochta|lagta)\s*$",
    re.IGNORECASE,
)

# List/enumeration patterns — "first... second..."
_ENUMERATION = re.compile(
    r"\b(first|firstly|second|secondly|one thing|another thing|also|"
    r"number one|number two|for one|on one hand)\b",
    re.IGNORECASE,
)

# Strong completion signals
_COMPLETION_SIGNALS = re.compile(
    r"(that'?s\s+(it|all|my\s+answer)|"
    r"I'?m\s+done|nothing\s+else|"
    r"that'?s\s+what\s+I\s+(think|want|mean|said)|"
    r"period|full\s+stop|"
    r"bas\s+itna|yehi\s+hai|kuch\s+nahi)\s*[.!]?\s*$",
    re.IGNORECASE,
)

# Question patterns — questions are almost always complete turns
_QUESTION_END = re.compile(r"\?\s*$")
_QUESTION_START = re.compile(
    r"^\s*(what|how|why|when|where|who|which|can|could|would|will|is|are|do|does|did)\b",
    re.IGNORECASE,
)


class TurnDetector:
    """
    Predicts whether the borrower has finished their turn.

    Returns a TurnState with:
    - is_complete: True if the borrower is likely done
    - confidence: 0.0-1.0 confidence in the prediction
    - reason: human-readable explanation

    Usage in session_orchestrator:
        turn = turn_detector.analyze(transcript, confidence, interims_history)
        if turn.is_complete:
            # fire LLM
        else:
            # wait for more speech (up to max_wait)
    """

    def __init__(
        self,
        max_wait_ms: int = 1500,       # max time to wait for continuation after uncertain turn
        min_words_complete: int = 3,    # minimum words for a complete turn
        velocity_window: int = 5,       # interim history size for velocity calculation
    ) -> None:
        self._max_wait_ms = max_wait_ms
        self._min_words_complete = min_words_complete
        self._velocity_window = velocity_window

        # Track interim evolution to detect "still typing"
        self._interim_history: deque[tuple[float, str]] = deque(maxlen=velocity_window)
        self._last_final_at: float = 0.0
        self._pending_turn_start: float = 0.0

    def feed_interim(self, transcript: str) -> None:
        """Feed interim transcripts to track speech velocity."""
        self._interim_history.append((time.monotonic(), transcript))

    def analyze(self, transcript: str, stt_confidence: float) -> "TurnState":
        """Analyze a final transcript and predict turn completion."""
        transcript = transcript.strip()
        words = transcript.split()
        n_words = len(words)

        # ── Definite completions ──────────────────────────────────────────────
        # Questions are complete turns
        if _QUESTION_END.search(transcript) or (
            _QUESTION_START.match(transcript) and n_words >= 4
        ):
            return TurnState(True, 0.95, "question_detected")

        # Explicit completion signals
        if _COMPLETION_SIGNALS.search(transcript):
            return TurnState(True, 0.95, "explicit_completion_signal")

        # Very short + high confidence = complete
        if n_words <= 2 and stt_confidence > 0.9:
            lower = transcript.lower().rstrip(".!,")
            if lower in ("no", "yes", "okay", "sure", "fine", "nope", "never"):
                return TurnState(True, 0.90, "short_definitive_response")

        # ── Definite continuations ────────────────────────────────────────────
        # Trailing conjunction
        if _TRAILING_CONJUNCTION.search(transcript):
            return TurnState(False, 0.90, "trailing_conjunction")

        # Trailing preposition
        if _TRAILING_PREPOSITION.search(transcript):
            return TurnState(False, 0.85, "trailing_preposition")

        # Incomplete verb phrase
        if _INCOMPLETE_VERB.search(transcript):
            return TurnState(False, 0.85, "incomplete_verb_phrase")

        # Too short to be complete
        if n_words < self._min_words_complete and not transcript.endswith((".", "!", "?")):
            return TurnState(False, 0.70, "too_short")

        # ── Heuristic scoring ─────────────────────────────────────────────────
        score = 0.5  # neutral baseline

        # Sentence-ending punctuation
        if transcript.endswith((".", "!", "?")):
            score += 0.25

        # Complete sentence structure (subject + verb detected)
        if re.search(r"\b(I|you|he|she|we|they|it)\b.*\b(is|am|are|was|were|have|had|will|can|do|did|want|need|paid|owe)\b", transcript, re.IGNORECASE):
            score += 0.15

        # Enumeration suggests more items coming
        if _ENUMERATION.search(transcript) and not transcript.endswith((".", "!")):
            score -= 0.20

        # Long utterances are more likely complete
        if n_words >= 10:
            score += 0.10
        elif n_words >= 6:
            score += 0.05

        # High STT confidence suggests clean endpoint
        if stt_confidence > 0.92:
            score += 0.05

        # Check speech velocity — if interims were still growing rapidly,
        # borrower might still be talking (Deepgram endpointed on a pause)
        velocity = self._compute_velocity()
        if velocity > 3.0:  # > 3 words/sec means speech was flowing
            score -= 0.15

        # Clamp
        score = max(0.0, min(1.0, score))

        is_complete = score >= 0.55
        return TurnState(is_complete, score, f"heuristic_score={score:.2f}")

    def _compute_velocity(self) -> float:
        """Compute words-per-second from recent interim history."""
        if len(self._interim_history) < 2:
            return 0.0

        first_ts, first_text = self._interim_history[0]
        last_ts, last_text = self._interim_history[-1]

        dt = last_ts - first_ts
        if dt < 0.1:
            return 0.0

        word_delta = len(last_text.split()) - len(first_text.split())
        return max(0.0, word_delta / dt)

    def reset(self) -> None:
        """Reset state between utterances."""
        self._interim_history.clear()
        self._last_final_at = time.monotonic()


class TurnState:
    """Result of turn-completion analysis."""
    __slots__ = ("is_complete", "confidence", "reason")

    def __init__(self, is_complete: bool, confidence: float, reason: str) -> None:
        self.is_complete = is_complete
        self.confidence = confidence
        self.reason = reason

    def __repr__(self) -> str:
        return f"TurnState(complete={self.is_complete}, conf={self.confidence:.2f}, reason={self.reason})"
