from __future__ import annotations

import re
import uuid

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.call import Call
from app.models.database.call_analysis import CallAnalysis
from app.models.schemas.call import FollowUpBrief
from app.services.follow_up.followup import build_follow_up_plan


_LOW_VALUE_PATTERNS = [
    re.compile(r"^(borrower:\s*)?(hi|hello|hey|yeah|yes|ok|okay)[.! ]*$", re.IGNORECASE),
    re.compile(r"^(agent:\s*)?(hi|hello|hey)[^a-zA-Z0-9]*", re.IGNORECASE),
    re.compile(r"attempt to collect a debt", re.IGNORECASE),
    re.compile(r"any information obtained will be used", re.IGNORECASE),
]


def _clean_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .")


def _is_low_value(text: str) -> bool:
    cleaned = _clean_line(text)
    if not cleaned:
        return True
    return any(pattern.search(cleaned) for pattern in _LOW_VALUE_PATTERNS)


def _normalize_fact(text: str) -> str:
    cleaned = _clean_line(text)
    cleaned = re.sub(r"^(Borrower:|Agent:)\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _snippets_from_transcript(text: str | None, limit: int = 3) -> list[str]:
    if not text:
        return []
    borrower_lines: list[str] = []
    other_lines: list[str] = []
    skip_prefixes = ("Agent: Hi, is", "Agent: Hello", "Agent: Hey ")
    snippets: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(skip_prefixes):
            continue
        if _is_low_value(line):
            continue
        if line.startswith("Borrower:"):
            borrower_lines.append(_normalize_fact(line))
        else:
            other_lines.append(_normalize_fact(line))
    for line in borrower_lines + other_lines:
        snippets.append(line)
        if len(snippets) >= limit:
            break
    return snippets


async def get_follow_up_source_call(
    db: AsyncSession,
    borrower_id: uuid.UUID | str,
    source_call_id: uuid.UUID | str | None = None,
) -> tuple[Call, CallAnalysis | None] | None:
    borrower_uuid = borrower_id if isinstance(borrower_id, uuid.UUID) else uuid.UUID(str(borrower_id))
    query = (
        select(Call, CallAnalysis)
        .outerjoin(CallAnalysis, CallAnalysis.ai_call_id == Call.id)
        .where(Call.borrower_id == borrower_uuid)
        .order_by(desc(Call.created_at))
    )
    if source_call_id:
        source_uuid = source_call_id if isinstance(source_call_id, uuid.UUID) else uuid.UUID(str(source_call_id))
        query = query.where(Call.id == source_uuid)
    else:
        query = query.where(
            or_(
                CallAnalysis.id.is_not(None),
                Call.recording_url.is_not(None),
            )
        )

    result = await db.execute(query.limit(1))
    row = result.first()
    if not row:
        return None
    return row[0], row[1]


async def build_follow_up_brief(
    db: AsyncSession,
    borrower_id: uuid.UUID | str,
    source_call_id: uuid.UUID | str | None = None,
) -> FollowUpBrief | None:
    source = await get_follow_up_source_call(db, borrower_id, source_call_id)
    if not source:
        return None

    call, analysis = source
    key_points = list(analysis.key_points or []) if analysis else []
    next_call_focus = list(analysis.next_call_talking_points or []) if analysis else []
    transcript_snippets = _snippets_from_transcript(analysis.transcript_text if analysis else None)

    summary = (
        analysis.borrower_characterization
        if analysis and analysis.borrower_characterization
        else "Previous call completed. Use the earlier conversation to continue instead of restarting cold."
    )
    if not next_call_focus and analysis and analysis.recommended_strategy:
        next_call_focus = [f"Lean into the {analysis.recommended_strategy} approach on this call."]
    if not key_points and transcript_snippets:
        key_points = transcript_snippets[:2]

    brief = FollowUpBrief(
        borrower_id=call.borrower_id,
        source_call_id=call.id,
        source_call_created_at=call.created_at,
        analysis_status=analysis.analysis_status if analysis else "missing",
        title="AI Follow-up Brief",
        summary=summary,
        key_points=key_points,
        next_call_focus=next_call_focus,
        suggested_opening="",
        transcript_snippets=transcript_snippets,
    )
    return brief.model_copy(update={"suggested_opening": build_follow_up_plan(brief).ui_opening})
