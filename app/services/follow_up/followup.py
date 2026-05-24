from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.schemas.call import FollowUpBrief


_FILLER_PATTERNS = (
    re.compile(r"^(hi|hello|hey|yeah|yes|okay|ok|hmm|mm+)[.! ]*$", re.IGNORECASE),
    re.compile(r"attempt to collect a debt", re.IGNORECASE),
    re.compile(r"any information obtained will be used", re.IGNORECASE),
)

_PROMISE_PATTERNS = (
    re.compile(r"\b(i will pay|i'll pay|i can pay|i said i will|promised|promise to pay)\b", re.IGNORECASE),
    re.compile(r"\b(pay|payment)\b.*\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    re.compile(r"\b(inr|rupees?|rs\.?)\b", re.IGNORECASE),
)

_HARDSHIP_PATTERNS = (
    re.compile(r"\b(salary|job|lost my job|medical|hospital|family issue|hardship|no money|cash flow|month end)\b", re.IGNORECASE),
)

_REFUSAL_PATTERNS = (
    re.compile(r"\b(can't pay|cannot pay|won't pay|not paying|refuse|not now)\b", re.IGNORECASE),
)


@dataclass
class FollowUpPlan:
    context_block: str
    ui_opening: str
    spoken_opening: str
    first_turn_instruction: str


def _clean(text: str) -> str:
    cleaned = re.sub(r"^(Borrower:|Agent:)\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .")


def _is_filler(text: str) -> bool:
    value = _clean(text)
    if not value:
        return True
    return any(pattern.search(value) for pattern in _FILLER_PATTERNS)


def _first_meaningful(items: list[str]) -> str:
    for item in items:
        cleaned = _clean(item)
        if cleaned and not _is_filler(cleaned):
            return cleaned
    return ""


def _pick_memory(brief: FollowUpBrief) -> str:
    candidates = [
        *brief.key_points,
        *brief.transcript_snippets,
        *brief.next_call_focus,
        brief.summary,
    ]
    cleaned = [_clean(item) for item in candidates if item]

    for item in cleaned:
        if any(pattern.search(item) for pattern in _PROMISE_PATTERNS) and not _is_filler(item):
            return item
    for item in cleaned:
        if any(pattern.search(item) for pattern in _HARDSHIP_PATTERNS) and not _is_filler(item):
            return item
    for item in cleaned:
        if any(pattern.search(item) for pattern in _REFUSAL_PATTERNS) and not _is_filler(item):
            return item
    return _first_meaningful(cleaned)


def _pick_focus(brief: FollowUpBrief) -> str:
    focus = _first_meaningful([*brief.next_call_focus, *brief.key_points])
    return focus or "confirm the next payment step clearly"


def _build_spoken_opening(memory: str, focus: str) -> str:
    if any(pattern.search(memory) for pattern in _PROMISE_PATTERNS):
        return (
            f"On our last call, you said {memory}. "
            "That payment has not come through yet. What changed?"
        )
    if any(pattern.search(memory) for pattern in _HARDSHIP_PATTERNS):
        return (
            f"Last time, you mentioned {memory}. "
            "I'm calling to check where things stand today and what you can pay now."
        )
    if any(pattern.search(memory) for pattern in _REFUSAL_PATTERNS):
        return (
            f"On our last call, you said {memory}. "
            "I'm following up today to understand what needs to happen to move this forward."
        )
    if memory:
        return (
            f"On our last call, you said {memory}. "
            f"I'm following up on that today and need to {focus.lower()}."
        )
    return "I'm following up on our last conversation and need to confirm the next payment step today."


def build_follow_up_plan(brief: FollowUpBrief) -> FollowUpPlan:
    memory = _pick_memory(brief)
    focus = _pick_focus(brief)
    spoken_opening = _build_spoken_opening(memory, focus)

    key_lines = "\n".join(f"- {item}" for item in brief.key_points if not _is_filler(item))
    focus_lines = "\n".join(f"- {item}" for item in brief.next_call_focus if not _is_filler(item))
    snippet_lines = "\n".join(f"- {_clean(item)}" for item in brief.transcript_snippets if not _is_filler(item))

    context_block = (
        "This is a follow-up call. Continue from the previous conversation naturally.\n"
        f"Previous call date: {brief.source_call_created_at.isoformat()}\n"
        f"Summary: {brief.summary}\n"
        f"Best remembered point: {memory or 'No strong prior point available'}\n"
        f"Key points:\n{key_lines or '- No strong key points available'}\n"
        f"Next-call focus:\n{focus_lines or '- Confirm the next payment step'}\n"
        f"Grounding snippets:\n{snippet_lines or '- No usable transcript snippets available'}"
    )

    first_turn_instruction = (
        "[FOLLOW-UP FIRST TURN]\n"
        f"After the debt disclosure, speak like a human follow-up caller and open with this exact idea: {spoken_opening}\n"
        "Do not sound like a fresh first call.\n"
        "Do not summarize analysis or mention reports.\n"
        "Reference the previous call directly, then ask one short payment-focused question.\n"
        "Keep it natural, professional, and concise."
    )

    return FollowUpPlan(
        context_block=context_block,
        ui_opening=spoken_opening,
        spoken_opening=spoken_opening,
        first_turn_instruction=first_turn_instruction,
    )
