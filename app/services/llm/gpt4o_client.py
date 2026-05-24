"""
GPT-4o client with streaming + function calling.
Implements sentence-boundary detection for early TTS dispatch.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.services.llm.function_registry import FUNCTION_REGISTRY

logger = logging.getLogger(__name__)

SENTENCE_ENDINGS = re.compile(r'(?<=[.!?])\s+')


@dataclass
class LLMResponse:
    text: str = ""
    function_name: Optional[str] = None
    function_args: dict = field(default_factory=dict)
    latency_ms: int = 0
    finish_reason: str = ""


class GPT4oClient:
    """
    Streaming GPT-4o client for real-time voice agent responses.

    Key design: streams tokens and dispatches TTS as soon as a full sentence
    is formed — without waiting for the full response. This is the primary
    latency optimization that brings end-to-end response time under 600ms.

    Fast-first-sentence mode: uses a smaller, faster model (gpt-4o-mini)
    to generate the first sentence, then switches to the main model for
    the rest. Reduces TTFT from ~500ms to ~150ms.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_llm_model
        self._max_tokens = settings.openai_llm_max_tokens
        self._temperature = settings.openai_llm_temperature
        self._fast_model = settings.openai_fast_model
        self._fast_max_tokens = settings.openai_fast_max_tokens

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: list[dict],
        on_sentence: "Callable[[str], Awaitable[None]] | None" = None,
    ) -> LLMResponse:
        """
        Stream a GPT-4o response. Calls on_sentence() as soon as each complete
        sentence is available (for immediate TTS dispatch).

        Returns the full LLMResponse after stream completes.
        """
        t0 = time.monotonic()
        result = LLMResponse()
        sentence_buffer = ""
        function_call_name = ""
        function_call_args = ""
        function_call_index = 0   # track first tool call only (ignore parallel calls)

        _new_model = any(self._model.startswith(p) for p in ("gpt-5", "o1", "o3", "o4"))
        # gpt-5+, o1, o3, o4 require max_completion_tokens; older models use max_tokens
        _token_kwarg = {"max_completion_tokens": self._max_tokens} if _new_model else {"max_tokens": self._max_tokens}
        # gpt-5+, o1, o3, o4 don't support custom temperature (only default 1)
        _temp_kwarg = {} if _new_model else {"temperature": self._temperature}

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system_prompt}] + conversation_history,
                tools=[{"type": "function", "function": f} for f in FUNCTION_REGISTRY],
                tool_choice="auto",
                **_token_kwarg,
                **_temp_kwarg,
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                finish_reason = chunk.choices[0].finish_reason

                # ── Text content ──────────────────────────────────────────────
                if delta.content:
                    token = delta.content
                    result.text += token
                    sentence_buffer += token

                    # Dispatch to TTS as soon as a sentence boundary is detected
                    if on_sentence and SENTENCE_ENDINGS.search(sentence_buffer):
                        parts = SENTENCE_ENDINGS.split(sentence_buffer)
                        for sentence in parts[:-1]:
                            sentence = sentence.strip()
                            if sentence:
                                await on_sentence(sentence)
                        sentence_buffer = parts[-1]

                # ── Function call accumulation ────────────────────────────────
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        # Only accumulate the first tool call (index 0).
                        # gpt-4o-mini sometimes fires parallel tool calls; concatenating
                        # all their args produces invalid JSON. We take the first and drop the rest.
                        if tc.index is not None and tc.index > 0:
                            continue
                        if tc.function:
                            if tc.function.name:
                                function_call_name += tc.function.name
                            if tc.function.arguments:
                                function_call_args += tc.function.arguments

                if finish_reason:
                    result.finish_reason = finish_reason

            # Flush any remaining sentence buffer
            if on_sentence and sentence_buffer.strip():
                await on_sentence(sentence_buffer.strip())

            # Parse function call if present
            if function_call_name:
                result.function_name = function_call_name
                try:
                    result.function_args = json.loads(function_call_args)
                except json.JSONDecodeError:
                    logger.warning("Could not parse function args: %s", function_call_args)

        except Exception as exc:
            logger.error("GPT-4o streaming error (model=%s): %s", self._model, exc)
            raise

        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result

    async def generate_fast_first_sentence(
        self,
        system_prompt: str,
        conversation_history: list[dict],
    ) -> str | None:
        """Generate ONLY the first sentence using a fast model for low TTFT.

        Returns the first sentence as a string, or None on failure.
        This runs concurrently with the main model — whichever produces
        a first sentence first wins. The main model's response continues
        to generate the remaining sentences.

        Typical latency: ~100-200ms TTFT (vs ~400-600ms for gpt-4o).
        """
        try:
            # Add instruction to generate only one short sentence
            fast_messages = [
                {"role": "system", "content": system_prompt},
                *conversation_history,
                {
                    "role": "user",
                    "content": (
                        "[INTERNAL: Generate ONLY the first sentence of your response. "
                        "Keep it under 15 words. Be direct. Do not continue beyond one sentence.]"
                    ),
                },
            ]

            _new_model = any(self._fast_model.startswith(p) for p in ("gpt-5", "o1", "o3", "o4"))
            _token_kwarg = {"max_completion_tokens": self._fast_max_tokens} if _new_model else {"max_tokens": self._fast_max_tokens}
            _temp_kwarg = {} if _new_model else {"temperature": self._temperature}

            stream = await self._client.chat.completions.create(
                model=self._fast_model,
                messages=fast_messages,
                **_token_kwarg,
                **_temp_kwarg,
                stream=True,
            )

            sentence = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    sentence += delta.content
                    # Stop at first sentence boundary
                    if SENTENCE_ENDINGS.search(sentence) or sentence.strip().endswith((".", "!", "?")):
                        break

            sentence = sentence.strip()
            if sentence:
                logger.debug("Fast first sentence (%s): '%s'", self._fast_model, sentence[:60])
                return sentence

        except Exception as exc:
            logger.debug("Fast first sentence failed (non-fatal): %s", exc)

        return None
