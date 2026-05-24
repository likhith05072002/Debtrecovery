"""Unit tests for LLM prompt builder."""
from decimal import Decimal
from app.services.llm.prompt_builder import (
    BorrowerContext, CampaignContext, build_system_prompt
)


def _make_borrower(**kwargs):
    defaults = dict(
        first_name="John",
        account_last4="4521",
        current_balance=Decimal("4250.00"),
        principal_amount=Decimal("5000.00"),
        days_past_due=60,
        debt_type="credit_card",
        original_creditor="Capital One",
        total_calls=3,
        successful_contacts=2,
        last_outcome="no_answer",
        engagement_score=0.4,
        avoidance_score=0.3,
        sentiment_trend="neutral",
        promise_kept_count=0,
        promise_made_count=0,
        preferred_language="en",
    )
    defaults.update(kwargs)
    return BorrowerContext(**defaults)


def _make_campaign(**kwargs):
    defaults = dict(
        strategy_type="negotiation",
        settlement_floor_pct=0.5,
        min_payment_monthly=Decimal("150.00"),
        max_extension_days=30,
    )
    defaults.update(kwargs)
    return CampaignContext(**defaults)


def test_prompt_contains_mini_miranda():
    prompt = build_system_prompt(_make_borrower(), _make_campaign(), "", "Apex", "Alex")
    assert "attempt to collect a debt" in prompt


def test_prompt_contains_borrower_balance():
    prompt = build_system_prompt(_make_borrower(), _make_campaign(), "", "Apex", "Alex")
    assert "4,250.00" in prompt


def test_negotiation_strategy_injected():
    prompt = build_system_prompt(_make_borrower(), _make_campaign(strategy_type="negotiation"), "", "Apex", "Alex")
    assert "NEGOTIATION" in prompt


def test_settlement_strategy_injected():
    prompt = build_system_prompt(_make_borrower(), _make_campaign(strategy_type="settlement"), "", "Apex", "Alex")
    assert "SETTLEMENT" in prompt


def test_opt_out_rule_present():
    prompt = build_system_prompt(_make_borrower(), _make_campaign(), "", "Apex", "Alex")
    assert "trigger_opt_out" in prompt
