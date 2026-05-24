"""
Gemini LLM client with streaming + function calling.
Implements sentence-boundary detection for early TTS dispatch.

Replaces OpenAI GPT-4o with Google Gemini (gemini-2.0-flash).
Same interface — session_orchestrator doesn't know the difference.
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

from google import genai
from google.genai import types

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


def _build_gemini_tools() -> list[types.Tool]:
    """Convert our OpenAI-format function registry to Gemini tool format."""
    function_declarations = []
    for fn in FUNCTION_REGISTRY:
        # Convert OpenAI JSON Schema to Gemini format
        params = fn.get("parameters", {})
        properties = {}
        required = params.get("required", [])

        for prop_name, prop_def in params.get("properties", {}).items():
            prop_type = prop_def.get("type", "string").upper()
            # Map JSON Schema types to Gemini types
            type_map = {
                "STRING": "STRING",
                "NUMBER": "NUMBER",
                "INTEGER": "INTEGER",
                "BOOLEAN": "BOOLEAN",
                "ARRAY": "ARRAY",
            }
            schema = types.Schema(
                type=type_map.get(prop_type, "STRING"),
                description=prop_def.get("description", ""),
            )
            if "enum" in prop_def:
                schema.enum = prop_def["enum"]
            properties[prop_name] = schema

        function_declarations.append(types.FunctionDeclaration(
            name=fn["name"],
            description=fn.get("description", ""),
            parameters=types.Schema(
                type="OBJECT",
                properties=properties,
                required=required,
            ),
        ))

    return [types.Tool(function_declarations=function_declarations)]


class GPT4oClient:
    """
    Streaming Gemini client for real-time voice agent responses.

    Key design: streams tokens and dispatches TTS as soon as a full sentence
    is formed — without waiting for the full response. This is the primary
    latency optimization that brings end-to-end response time under 600ms.

    Despite the class name (kept for backward compatibility), this now uses
    Google Gemini instead of OpenAI GPT-4o.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._max_tokens = settings.gemini_max_tokens
        self._temperature = settings.gemini_temperature
        self._fast_model = settings.gemini_fast_model
        self._tools = _build_gemini_tools()

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: list[dict],
        on_sentence: "Callable[[str], Awaitable[None]] | None" = None,
    ) -> LLMResponse:
        """
        Stream a Gemini response. Calls on_sentence() as soon as each complete
        sentence is available (for immediate TTS dispatch).

        Returns the full LLMResponse after stream completes.
        """
        t0 = time.monotonic()
        result = LLMResponse()
        sentence_buffer = ""
        function_call_name = ""
        function_call_args = {}

        # Convert OpenAI-format messages to Gemini format
        gemini_contents = []
        for msg in conversation_history:
            role = msg["role"]
            content = msg.get("content", "")
            if role == "assistant":
                gemini_contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=content)],
                ))
            elif role in ("user", "system"):
                gemini_contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=content)],
                ))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=self._max_tokens,
            temperature=self._temperature,
            tools=self._tools,
        )

        try:
            response = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=gemini_contents,
                config=config,
            )

            async for chunk in response:
                if not chunk.candidates:
                    continue

                candidate = chunk.candidates[0]

                # Check for function calls
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        # Text content
                        if part.text:
                            token = part.text
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

                        # Function call
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            function_call_name = fc.name
                            function_call_args = dict(fc.args) if fc.args else {}

                # Check finish reason
                if candidate.finish_reason:
                    result.finish_reason = str(candidate.finish_reason)

            # Flush remaining sentence buffer
            if on_sentence and sentence_buffer.strip():
                await on_sentence(sentence_buffer.strip())

            # Set function call if present
            if function_call_name:
                result.function_name = function_call_name
                result.function_args = function_call_args

        except Exception as exc:
            logger.error("Gemini streaming error (model=%s): %s", self._model, exc)
            raise

        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result

    async def generate_fast_first_sentence(
        self,
        system_prompt: str,
        conversation_history: list[dict],
    ) -> str | None:
        """Generate ONLY the first sentence using a fast model for low TTFT.

        Uses gemini-2.0-flash-lite (~100ms TTFT).
        """
        try:
            gemini_contents = []
            for msg in conversation_history:
                role = msg["role"]
                content = msg.get("content", "")
                if role == "assistant":
                    gemini_contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)],
                    ))
                elif role in ("user", "system"):
                    gemini_contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=content)],
                    ))

            # Add instruction for first sentence only
            gemini_contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text="[INTERNAL: Generate ONLY the first sentence of your response. "
                         "Keep it under 15 words. Be direct. Do not continue beyond one sentence.]"
                )],
            ))

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=60,
                temperature=self._temperature,
            )

            response = await self._client.aio.models.generate_content_stream(
                model=self._fast_model,
                contents=gemini_contents,
                config=config,
            )

            sentence = ""
            async for chunk in response:
                if not chunk.candidates:
                    continue
                candidate = chunk.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            sentence += part.text
                            if SENTENCE_ENDINGS.search(sentence) or sentence.strip().endswith((".", "!", "?")):
                                break

            sentence = sentence.strip()
            if sentence:
                logger.debug("Fast first sentence (%s): '%s'", self._fast_model, sentence[:60])
                return sentence

        except Exception as exc:
            logger.debug("Fast first sentence failed (non-fatal): %s", exc)

        return None
