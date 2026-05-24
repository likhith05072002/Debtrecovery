"""
Gemini structured analysis for call transcripts.

Uses JSON output for reliable structured output. Non-streaming — we need
the full JSON blob, not incremental tokens. Low temperature for consistency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.agents.call_intelligence.prompt import SYSTEM_PROMPT, build_analysis_prompt
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    overall_sentiment: str
    sentiment_score: float
    willingness_to_pay: str
    payment_intent_score: float
    key_points: list[str] = field(default_factory=list)
    borrower_characterization: str = ""
    repayment_probability: float = 0.5
    repayment_probability_reason: str = ""
    recommended_strategy: str = "reminder"
    next_call_talking_points: list[str] = field(default_factory=list)
    model_used: str = "gemini-2.0-flash"


class CallAnalyzer:
    """
    Sends a call transcript to Gemini and gets structured intelligence back.
    Designed for post-call batch processing (not real-time).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def analyze_transcript(
        self,
        transcript_text: str,
        borrower_context: dict,
    ) -> AnalysisResult:
        """
        Send transcript + borrower context to Gemini.
        Returns a validated AnalysisResult with all fields clamped to valid ranges.
        """
        user_prompt = build_analysis_prompt(transcript_text, borrower_context)

        logger.info("Analyzing transcript with %s (%d chars)", self._model, len(transcript_text))

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_prompt)],
            )],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=1000,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        raw_json = response.text
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.error("Gemini returned invalid JSON: %s", raw_json[:500])
            raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc

        result = self._build(data)
        logger.info(
            "Analysis complete: sentiment=%s willingness=%s repayment_prob=%.2f",
            result.overall_sentiment, result.willingness_to_pay, result.repayment_probability,
        )
        return result

    def _build(self, data: dict) -> AnalysisResult:
        """Validate output and clamp all numeric fields to valid ranges."""
        valid_sentiments = {"hostile", "negative", "neutral", "positive", "cooperative"}
        valid_willingness = {"high", "medium", "low", "refused"}
        valid_strategies = {"reminder", "negotiation", "settlement", "escalation"}

        sentiment = data.get("overall_sentiment", "neutral")
        if sentiment not in valid_sentiments:
            sentiment = "neutral"

        willingness = data.get("willingness_to_pay", "low")
        if willingness not in valid_willingness:
            willingness = "low"

        strategy = data.get("recommended_strategy", "reminder")
        if strategy not in valid_strategies:
            strategy = "reminder"

        return AnalysisResult(
            overall_sentiment=sentiment,
            sentiment_score=max(-1.0, min(1.0, float(data.get("sentiment_score", 0.0)))),
            willingness_to_pay=willingness,
            payment_intent_score=max(0.0, min(1.0, float(data.get("payment_intent_score", 0.0)))),
            key_points=list(data.get("key_points", [])),
            borrower_characterization=str(data.get("borrower_characterization", "")),
            repayment_probability=max(0.0, min(1.0, float(data.get("repayment_probability", 0.5)))),
            repayment_probability_reason=str(data.get("repayment_probability_reason", "")),
            recommended_strategy=strategy,
            next_call_talking_points=list(data.get("next_call_talking_points", [])),
            model_used=self._model,
        )
