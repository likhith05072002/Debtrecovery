"""
Real-time sentiment scoring for borrower speech.

Uses a lightweight rule-based lexicon for sub-10ms latency on the hot path,
augmented with a transformer model for batch post-call analysis.

Sentiment score: -1.0 (very negative/hostile) to +1.0 (very positive/cooperative)
Labels: hostile | negative | neutral | positive | cooperative
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── Lexicon-based fast sentiment (used in real-time hot path) ─────────────────

POSITIVE_WORDS = {
    "okay", "ok", "yes", "sure", "alright", "fine", "great",
    "understand", "absolutely", "certainly", "appreciate", "thank",
    "help", "willing", "agree", "deal", "accept", "happy", "cooperate",
}

NEGATIVE_WORDS = {
    "no", "not", "never", "refuse", "cannot", "won't", "can't", "don't",
    "difficult", "hard", "problem", "issue", "wrong", "unfair",
    "annoying", "ridiculous", "impossible", "sick", "tired",
}

HOSTILE_WORDS = {
    "sue", "lawyer", "attorney", "harassment", "illegal", "report",
    "stupid", "idiot", "hate", "angry", "furious", "threatening", "ridiculous",
    "scam", "fraud", "fake", "lies", "lying",
}

HARDSHIP_WORDS = {
    "lost", "job", "unemployed", "sick", "hospital", "medical", "divorce",
    "struggling", "broke", "bankrupt", "disability", "laid off", "fired",
    "cannot afford", "no money", "tight",
}


@dataclass
class SentimentResult:
    score: float           # -1.0 to 1.0
    label: str             # hostile | negative | neutral | positive | cooperative
    hardship_detected: bool = False
    hostile_detected: bool = False


def analyze_sentiment(text: str) -> SentimentResult:
    """
    Fast lexicon-based sentiment analysis for real-time use.
    Returns a SentimentResult in <1ms.
    """
    words = set(re.findall(r"\b\w+\b", text.lower()))

    pos_count = len(words & POSITIVE_WORDS)
    neg_count = len(words & NEGATIVE_WORDS)
    hostile_count = len(words & HOSTILE_WORDS)
    hardship_count = len(words & HARDSHIP_WORDS)

    total = pos_count + neg_count + hostile_count + 1
    raw_score = (pos_count - neg_count - hostile_count * 2) / total
    score = max(-1.0, min(1.0, raw_score))

    if hostile_count >= 2 or score < -0.6:
        label = "hostile"
    elif score < -0.2:
        label = "negative"
    elif score > 0.4:
        label = "cooperative"
    elif score > 0.1:
        label = "positive"
    else:
        label = "neutral"

    return SentimentResult(
        score=round(score, 4),
        label=label,
        hardship_detected=hardship_count >= 2,
        hostile_detected=hostile_count >= 2,
    )


def extract_entities(text: str) -> dict:
    """
    Extract structured entities from borrower speech:
    - rupee amounts
    - dates
    - payment methods
    """
    entities: dict = {
        "amounts": [],
        "dates": [],
        "payment_methods": [],
        "hardship_signals": [],
    }

    # Rupee amounts: ₹X, INR X, X rupees
    amounts = re.findall(
        r"₹\s?[\d,]+(?:\.\d{2})?"
        r"|\bINR\s*[\d,]+(?:\.\d{2})?\b"
        r"|\b\d[\d,]*(?:\.\d{2})?\s*(?:rupees?|rs\.?|inr)\b",
        text,
        re.IGNORECASE,
    )
    entities["amounts"] = amounts

    # Simple date patterns
    dates = re.findall(
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b"
        r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
        r"|\bnext\s+(?:week|month|monday|tuesday|wednesday|thursday|friday)\b",
        text, re.IGNORECASE
    )
    entities["dates"] = dates

    # Payment methods
    if re.search(r"\b(check|cheque)\b", text, re.IGNORECASE):
        entities["payment_methods"].append("check")
    if re.search(r"\b(credit card|debit card|card)\b", text, re.IGNORECASE):
        entities["payment_methods"].append("card")
    if re.search(r"\b(bank\s+transfer|ach|wire)\b", text, re.IGNORECASE):
        entities["payment_methods"].append("ach")

    # Hardship signals
    hardship_text = text.lower()
    for phrase in ["lost my job", "laid off", "unemployed", "in the hospital", "medical bills", "disability", "going through a divorce"]:
        if phrase in hardship_text:
            entities["hardship_signals"].append(phrase)

    return entities
