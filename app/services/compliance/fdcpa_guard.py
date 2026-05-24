"""
FDCPA compliance guard — 3-layer protection system.

Layer 1: pre_call_compliance_check() — gate before any call attempt
Layer 2: check_agent_response()     — filter every LLM-generated response
Layer 3: check_borrower_speech()    — detect opt-out/dispute triggers in real time

This module runs synchronously in the hot path (during live calls).
Any violation causes immediate action without waiting for post-processing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database.borrower import Borrower
from app.models.database.compliance import ComplianceEvent
from app.services.memory.redis_session import is_dnc
from app.utils.crypto import hash_pii, decrypt_pii

logger = logging.getLogger(__name__)

# ── Prohibited output patterns (FDCPA §806, §807) ─────────────────────────────
PROHIBITED_PATTERNS: list[re.Pattern] = [
    # False legal threats (arrest/jail/prosecution — always illegal)
    re.compile(r"\b(will|going to|you will)\s+(be\s+)?(arrest|jail|prison|prosecut)", re.IGNORECASE),
    # Direct lawsuit threats only ("I will sue you", "we will file a lawsuit against you")
    # Legitimate consequence mentions ("may be referred to legal", "collections attorney") are allowed
    re.compile(r"\b(I will|we will|I'm going to|we're going to)\s+(file a\s+)?sue\b", re.IGNORECASE),
    re.compile(r"\b(sue|suing)\s+you\b", re.IGNORECASE),
    # Harassment / abusive language
    re.compile(r"\b(stupid|idiot|deadbeat|loser|pathetic|worthless)\b", re.IGNORECASE),
    re.compile(r"\b(kill|hurt|harm|destroy)\s+(you|them|your)\b", re.IGNORECASE),
    # Third-party disclosure (only triggers outside borrower-confirmed calls)
    re.compile(r"(publish|tell|notify|inform)\s+(your\s+)?(friend|family|employer|neighbor|boss)", re.IGNORECASE),
    # False urgency / misrepresentation
    re.compile(r"\b(police|sheriff|marshal)\s+(will|is going to|are coming)", re.IGNORECASE),
]

# ── Opt-out triggers (borrower speech) ────────────────────────────────────────
OPT_OUT_TRIGGERS: list[str] = [
    "stop calling", "don't call", "do not call", "cease and desist",
    "never call again", "remove my number", "take me off",
    "i'll sue", "my lawyer", "file a complaint", "cfpb",
    "attorney general", "this is harassment", "stop contacting me",
    "i want you to stop", "never contact me",
]

# ── Dispute triggers (borrower speech) ───────────────────────────────────────
DISPUTE_TRIGGERS: list[str] = [
    "not my debt", "i don't owe", "wrong person", "identity theft",
    "dispute this", "validate the debt", "verify this debt",
    "that's not mine", "never had an account", "fraud",
    # NOTE: "already paid" intentionally excluded — it is a soft payment claim routed to
    # clarification mode in session_orchestrator._detect_soft_dispute(), not a formal dispute.
]


@dataclass
class ComplianceAction:
    action_type: str     # "opt_out" | "dispute" | "blocked"
    trigger: str
    severity: str = "warning"


@dataclass
class GuardResult:
    blocked: bool
    text: str = ""
    reason: str = ""
    pattern: str = ""


# ── Layer 1: Pre-call gate ────────────────────────────────────────────────────

class FDCPAViolationError(Exception):
    """Raised when a pre-call compliance check fails — do not place the call."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def pre_call_compliance_check(borrower: Borrower, db: AsyncSession) -> None:
    """
    Run all pre-call compliance checks before placing an outbound call.
    Raises FDCPAViolationError if any check fails.
    Also logs a ComplianceEvent for every violation.
    """
    settings = get_settings()
    reasons = []

    # 1. Opted out
    if borrower.opted_out:
        reasons.append("opted_out")

    # 2. DNC flag on record
    if borrower.do_not_call:
        reasons.append("do_not_call_flag")

    # 3. DNC in Redis (real-time)
    phone_hash = hash_pii(decrypt_pii(borrower.phone_e164))
    if await is_dnc(phone_hash):
        reasons.append("dnc_redis")

    # 4. Bankruptcy
    if borrower.bankruptcy_filed:
        reasons.append("bankruptcy_filed")

    # 5. Deceased
    if borrower.deceased:
        reasons.append("deceased")

    # 6. Call window check (8 AM – 9 PM local borrower time)
    try:
        tz = pytz.timezone(borrower.time_zone)
        local_now = datetime.now(tz)
        hour = local_now.hour
        if not (settings.fdcpa_call_window_start <= hour < settings.fdcpa_call_window_end):
            reasons.append(f"outside_call_window (local hour={hour})")
    except Exception:
        pass  # If TZ lookup fails, allow call — don't block on infra errors

    # 7. TCPA consent check for automated calls
    if not borrower.consent_recorded:
        reasons.append("no_tcpa_consent")

    if reasons:
        reason_str = ", ".join(reasons)
        # Log compliance event
        event = ComplianceEvent(
            borrower_id=borrower.id,
            event_type="pre_call_check_failed",
            severity="violation" if "opted_out" in reasons or "dnc" in reasons else "warning",
            description=f"Pre-call check blocked: {reason_str}",
            auto_actioned=True,
        )
        db.add(event)
        raise FDCPAViolationError(reason_str)


# ── Layer 2: LLM response filter ──────────────────────────────────────────────

def check_agent_response(text: str) -> GuardResult:
    """
    Scan LLM-generated text for prohibited patterns.
    Returns GuardResult(blocked=True) if any match is found.
    Called synchronously in the hot path before TTS dispatch.
    """
    for pattern in PROHIBITED_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.warning("FDCPA guard blocked response: pattern=%s match=%s", pattern.pattern, match.group())
            return GuardResult(
                blocked=True,
                reason="prohibited_language",
                pattern=pattern.pattern,
            )
    return GuardResult(blocked=False, text=text)


# ── Layer 3: Borrower speech scanner ─────────────────────────────────────────

def check_borrower_speech(transcript: str) -> list[ComplianceAction]:
    """
    Scan borrower's speech for opt-out or dispute triggers.
    Returns a list of actions that must be taken immediately.
    Called synchronously after every final STT transcript.
    """
    actions: list[ComplianceAction] = []
    lower = transcript.lower()

    for trigger in OPT_OUT_TRIGGERS:
        if trigger in lower:
            logger.info("Opt-out trigger detected: '%s' in transcript", trigger)
            actions.append(ComplianceAction(action_type="opt_out", trigger=trigger, severity="violation"))
            break  # One opt-out action is enough

    for trigger in DISPUTE_TRIGGERS:
        if trigger in lower:
            logger.info("Dispute trigger detected: '%s' in transcript", trigger)
            actions.append(ComplianceAction(action_type="dispute", trigger=trigger, severity="warning"))
            break

    return actions
