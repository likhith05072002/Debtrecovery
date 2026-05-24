from datetime import datetime, timezone
from uuid import uuid4

from app.models.schemas.call import FollowUpBrief
from app.services.follow_up.followup import build_follow_up_plan


def _make_brief(**kwargs) -> FollowUpBrief:
    defaults = dict(
        borrower_id=uuid4(),
        source_call_id=uuid4(),
        source_call_created_at=datetime.now(timezone.utc),
        analysis_status="completed",
        title="AI Follow-up Brief",
        summary="Borrower said salary was delayed and asked for more time.",
        key_points=["Borrower said they would pay INR 500 on Friday."],
        next_call_focus=["Confirm whether the INR 500 payment can be made today."],
        suggested_opening="",
        transcript_snippets=["Borrower: I will pay 500 rupees on Friday."],
    )
    defaults.update(kwargs)
    return FollowUpBrief(**defaults)


def test_followup_plan_prefers_payment_commitment():
    plan = build_follow_up_plan(_make_brief())
    assert "you said" in plan.spoken_opening.lower()
    assert "what changed?" in plan.spoken_opening.lower()
    assert "INR 500" in plan.spoken_opening


def test_followup_plan_ignores_filler_and_uses_focus():
    brief = _make_brief(
        key_points=["Borrower: Yeah. Hi."],
        transcript_snippets=["Borrower: Yeah. Hi."],
        next_call_focus=["Clarify the missed payment commitment."],
        summary="Borrower avoided confirming the promised payment date.",
    )
    plan = build_follow_up_plan(brief)
    assert "yeah. hi" not in plan.spoken_opening.lower()
    assert "missed payment commitment" in plan.spoken_opening.lower() or "payment" in plan.spoken_opening.lower()
