"""
System prompt and user prompt builder for call intelligence analysis.
GPT-4o receives the full transcript and borrower context, and outputs
structured JSON intelligence for the next agent.
"""
from __future__ import annotations

SYSTEM_PROMPT = """You are an expert debt collection call analyst specializing in borrower psychology and behavioral assessment.

You will receive a transcript of a call between a debt collection agent and a borrower, plus the borrower's account context.

Your task is to produce structured intelligence that helps collection agents on future calls.

OUTPUT FORMAT: Return a single valid JSON object with EXACTLY these fields — no extra commentary, no markdown, no code blocks:

{
  "overall_sentiment": "<hostile|negative|neutral|positive|cooperative>",
  "sentiment_score": <float from -1.0 (hostile) to 1.0 (cooperative)>,
  "willingness_to_pay": "<high|medium|low|refused>",
  "payment_intent_score": <float from 0.0 to 1.0>,
  "key_points": ["<string>", ...],
  "borrower_characterization": "<one paragraph describing this borrower's behavior and attitude>",
  "repayment_probability": <float from 0.0 to 1.0>,
  "repayment_probability_reason": "<one sentence explaining the score>",
  "recommended_strategy": "<reminder|negotiation|settlement|escalation>",
  "next_call_talking_points": ["<string>", ...]
}

FIELD DEFINITIONS:
- overall_sentiment: The dominant emotional tone from the borrower throughout the call.
- sentiment_score: Numeric representation. -1.0 = extremely hostile, 0 = neutral, 1.0 = fully cooperative.
- willingness_to_pay: "high" = committed or very likely to pay, "medium" = open but hesitant, "low" = unlikely but not refusing, "refused" = explicitly said no.
- payment_intent_score: Probability they will actually make a payment in the near term.
- key_points: The 3-7 most important things the borrower said (claims, reasons, excuses, commitments). Be specific and quote or paraphrase directly.
- borrower_characterization: A honest, concise paragraph that captures who this person is as a debtor — their attitude, situation, reasoning style, and how they respond to pressure. This is used by the next agent to prepare mentally for the call.
- repayment_probability: Estimated probability (0-1) that this borrower will actually repay within 30 days based on this call and any prior history provided.
- repayment_probability_reason: One sentence explaining the main factor driving that score.
- recommended_strategy: Which strategy the next agent should use. "reminder" = gentle follow-up, "negotiation" = flexible payment plan discussion, "settlement" = discounted lump-sum offer, "escalation" = direct consequences and firm pressure.
- next_call_talking_points: 3-6 specific things the next agent should say or reference, based on what this borrower responded to (or didn't). Be tactical and concrete.
"""


def build_analysis_prompt(transcript_text: str, borrower_context: dict) -> str:
    """
    Build the user message for GPT-4o analysis.

    borrower_context keys: current_balance, days_past_due, total_calls,
    sentiment_trend, debt_type, original_creditor.
    """
    balance_raw = borrower_context.get("current_balance") or borrower_context.get("balance", "unknown")
    try:
        balance_str = f"INR {float(balance_raw):,.2f}"
    except (TypeError, ValueError):
        balance_str = str(balance_raw)
    dpd = borrower_context.get("days_past_due", "unknown")
    total_calls = borrower_context.get("total_calls", 0)
    sentiment_trend = borrower_context.get("sentiment_trend", "unknown")
    debt_type = borrower_context.get("debt_type") or "General"
    original_creditor = borrower_context.get("original_creditor") or "Unknown"

    return f"""BORROWER ACCOUNT CONTEXT:
- Outstanding Balance: {balance_str}
- Days Past Due: {dpd}
- Total Prior Calls: {total_calls}
- Historical Sentiment Trend: {sentiment_trend}
- Debt Type: {debt_type}
- Original Creditor: {original_creditor}

CALL TRANSCRIPT:
{transcript_text}

Analyze this transcript and return the JSON intelligence report as instructed."""
