"""Unit tests for FDCPA compliance guard."""
from app.services.compliance.fdcpa_guard import (
    check_agent_response,
    check_borrower_speech,
    GuardResult,
    ComplianceAction,
)


def test_allows_clean_response():
    result = check_agent_response("I understand. Would you be able to make a payment of ₹150 on April 1st?")
    assert not result.blocked


def test_blocks_false_legal_threat():
    result = check_agent_response("You will be arrested if you don't pay.")
    assert result.blocked
    assert result.reason == "prohibited_language"


def test_blocks_abusive_language():
    result = check_agent_response("You are a deadbeat who never pays.")
    assert result.blocked


def test_detects_opt_out_trigger():
    actions = check_borrower_speech("Please stop calling me, I want to cease and desist.")
    opt_out_actions = [a for a in actions if a.action_type == "opt_out"]
    assert len(opt_out_actions) >= 1


def test_detects_dispute_trigger():
    actions = check_borrower_speech("This is not my debt, I've never had this account.")
    dispute_actions = [a for a in actions if a.action_type == "dispute"]
    assert len(dispute_actions) >= 1


def test_clean_borrower_speech_no_actions():
    actions = check_borrower_speech("Yeah, I can pay ₹200 next Friday.")
    assert len(actions) == 0
