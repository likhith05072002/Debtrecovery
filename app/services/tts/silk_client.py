"""
Rumik Silk TTS client — expressive multi-Indic voice synthesis.

Silk is a transformer-based TTS model trained for AI companions.
Key advantages over ElevenLabs for this use case:
- Native Indic language support (Hindi, Tamil, Malayalam, Kannada, Bengali)
- Code-switching (Hinglish, Tanglish) without quality loss
- Emotional mid-sentence tagging: <whisper>, <firm>, <empathetic>
- ~300ms average latency
- Romanized script input (matches GPT-4o output)

API integration designed from Silk's architecture:
- Transformer next-token prediction → discrete audio codes → waveform
- Streaming chunks as they're generated
- PCM output resampled to mulaw 8kHz for Twilio

The API interface is built to match the expected pattern once beta access
is granted. Update SILK_API_URL and auth when docs are available.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncGenerator

import httpx

from app.config import get_settings
from app.services.tts.base import TTSProvider
from app.utils.audio_utils import chunk_audio, pcm24k_to_mulaw8k, pcm16k_to_mulaw8k

logger = logging.getLogger(__name__)

# ── Silk API configuration ───────────────────────────────────────────────────
# Update these when Silk API docs become available
SILK_API_URL = "https://api.rumik.ai/v1/tts/stream"
SILK_WS_URL = "wss://api.rumik.ai/v1/tts/ws"

# Silk supports these languages natively (no need for romanization workarounds)
SILK_NATIVE_LANGUAGES = {"en", "hi", "ta", "ml", "kn", "bn", "te"}

# Emotional tags that Silk supports mid-sentence
SILK_EMOTION_TAGS = {
    "neutral", "firm", "empathetic", "whisper", "urgent",
    "reassuring", "professional", "warm", "stern",
}

# Language-specific voice IDs (update when Silk provides voice catalog)
SILK_VOICE_MAP: dict[str, str] = {
    "en": "silk-en-male-professional",
    "hi": "silk-hi-male-professional",
    "kn": "silk-kn-male-professional",
    "te": "silk-te-male-professional",
    "ta": "silk-ta-male-professional",
    "ml": "silk-ml-male-professional",
    "bn": "silk-bn-male-professional",
}

# In-process cache for pre-warmed utterances
_silk_cache: dict[str, list[bytes]] = {}


class SilkTTSClient(TTSProvider):
    """
    Streaming Silk TTS client for real-time voice agent responses.

    Yields mulaw 8kHz audio chunks suitable for Twilio Media Streams.
    Falls back to ElevenLabs if Silk API is unavailable.
    """

    def __init__(self, language: str = "en", voice_id: str | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.silk_api_key
        self._language = language
        self._voice_id = voice_id or SILK_VOICE_MAP.get(language, SILK_VOICE_MAP["en"])
        self._model_id = settings.silk_model_id
        self._sample_rate = settings.silk_sample_rate  # expected: 24000 or 16000

        # Emotion state — can be set per-turn by the orchestrator
        self._current_emotion: str = "professional"

    @property
    def provider_name(self) -> str:
        return "silk"

    def set_emotion(self, emotion: str) -> None:
        """Set the emotional tone for the next synthesis call.

        Silk supports mid-sentence emotional tagging. This sets the default
        emotion for the entire utterance. For mid-sentence changes, embed
        tags directly in the text: "<empathetic> I understand your situation."
        """
        if emotion in SILK_EMOTION_TAGS:
            self._current_emotion = emotion
        else:
            logger.warning("Unknown Silk emotion '%s', keeping '%s'", emotion, self._current_emotion)

    async def pre_warm(self, text: str) -> None:
        """Pre-generate and cache TTS audio for zero-latency playback."""
        if text in _silk_cache:
            return
        chunks: list[bytes] = []
        async for chunk in self._generate(text):
            chunks.append(chunk)
        _silk_cache[text] = chunks
        logger.debug("Silk pre-warm complete for: %.40s", text)

    async def synthesize_stream(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized speech as mulaw 8kHz chunks.

        Serves from cache if pre_warm() was called.
        Falls back to ElevenLabs on API error.
        """
        if text in _silk_cache:
            logger.debug("Silk cache hit: %.40s", text)
            for chunk in _silk_cache[text]:
                yield chunk
                await asyncio.sleep(0)
            return

        async for chunk in self._generate(text, chunk_size=chunk_size):
            yield chunk

    async def _generate(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Call Silk API, stream audio, convert to mulaw 8kHz for Twilio."""

        if not self._api_key:
            logger.warning("Silk API key not set, falling back to ElevenLabs")
            async for chunk in self._fallback_elevenlabs(text):
                yield chunk
            return

        # Prepare emotion-tagged text if emotion is set
        tagged_text = text
        if self._current_emotion != "neutral":
            tagged_text = f"<{self._current_emotion}> {text}"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        }
        payload = {
            "text": tagged_text,
            "voice_id": self._voice_id,
            "model_id": self._model_id,
            "language": self._language,
            "sample_rate": self._sample_rate,
            "output_format": "pcm_s16le",
            "emotion": self._current_emotion,
            "speed": 1.0,
            "stream": True,
        }

        t0 = time.monotonic()
        first_chunk = True

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", SILK_API_URL, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.error(
                            "Silk API %d (voice=%s model=%s) body=%s — falling back to ElevenLabs",
                            response.status_code, self._voice_id, self._model_id, body[:300],
                        )
                        async for chunk in self._fallback_elevenlabs(text):
                            yield chunk
                        return

                    async for raw_chunk in response.aiter_bytes(chunk_size):
                        if first_chunk:
                            latency_ms = int((time.monotonic() - t0) * 1000)
                            logger.info(
                                "Silk TTS active: voice=%s emotion=%s first_chunk=%dms",
                                self._voice_id, self._current_emotion, latency_ms,
                            )
                            try:
                                from app.monitoring.metrics import tts_latency
                                tts_latency.observe(latency_ms)
                            except ImportError:
                                pass
                            first_chunk = False

                        # Convert PCM to mulaw 8kHz for Twilio
                        if self._sample_rate == 24000:
                            mulaw_chunk = pcm24k_to_mulaw8k(raw_chunk)
                        elif self._sample_rate == 16000:
                            mulaw_chunk = pcm16k_to_mulaw8k(raw_chunk)
                        else:
                            # Assume 8kHz PCM, just convert to mulaw
                            import audioop
                            mulaw_chunk = audioop.lin2ulaw(raw_chunk, 2)

                        yield mulaw_chunk

        except httpx.TimeoutException:
            logger.error("Silk API timeout — falling back to ElevenLabs")
            async for chunk in self._fallback_elevenlabs(text):
                yield chunk
        except Exception as exc:
            logger.error("Silk streaming error: %s — falling back to ElevenLabs", exc)
            async for chunk in self._fallback_elevenlabs(text):
                yield chunk

    async def _fallback_elevenlabs(self, text: str) -> AsyncGenerator[bytes, None]:
        """Fall back to ElevenLabs when Silk is unavailable."""
        from app.services.tts.elevenlabs_client import ElevenLabsTTSClient
        fallback = ElevenLabsTTSClient(language=self._language)
        async for chunk in fallback.synthesize_stream(text):
            yield chunk


class SilkWebSocketClient(TTSProvider):
    """
    WebSocket-based Silk TTS client for lowest possible latency.

    Maintains a persistent WebSocket connection to Silk, avoiding
    per-request connection overhead. Ideal for the real-time call pipeline
    where every millisecond counts.

    Use this when:
    - Call is established and ongoing (persistent connection amortizes setup)
    - Sub-200ms first-chunk latency is required

    Use SilkTTSClient (HTTP) when:
    - Pre-warming utterances during call setup
    - One-off synthesis (connection overhead doesn't matter)
    """

    def __init__(self, language: str = "en", voice_id: str | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.silk_api_key
        self._language = language
        self._voice_id = voice_id or SILK_VOICE_MAP.get(language, SILK_VOICE_MAP["en"])
        self._model_id = settings.silk_model_id
        self._sample_rate = settings.silk_sample_rate
        self._ws = None
        self._current_emotion: str = "professional"

    @property
    def provider_name(self) -> str:
        return "silk-ws"

    async def connect(self) -> None:
        """Open persistent WebSocket connection to Silk."""
        import websockets

        headers = {"Authorization": f"Bearer {self._api_key}"}
        params = (
            f"?voice_id={self._voice_id}"
            f"&model_id={self._model_id}"
            f"&language={self._language}"
            f"&sample_rate={self._sample_rate}"
            f"&output_format=pcm_s16le"
        )
        self._ws = await websockets.connect(
            SILK_WS_URL + params,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )
        logger.info("Silk WebSocket connected: voice=%s lang=%s", self._voice_id, self._language)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.debug("Silk WebSocket closed")

    def set_emotion(self, emotion: str) -> None:
        if emotion in SILK_EMOTION_TAGS:
            self._current_emotion = emotion

    async def synthesize_stream(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Send text via WebSocket, stream audio chunks back."""
        import json

        if not self._ws or self._ws.closed:
            # Fallback to HTTP if WebSocket not connected
            http_client = SilkTTSClient(language=self._language, voice_id=self._voice_id)
            async for chunk in http_client.synthesize_stream(text, chunk_size):
                yield chunk
            return

        tagged_text = text
        if self._current_emotion != "neutral":
            tagged_text = f"<{self._current_emotion}> {text}"

        # Send synthesis request
        await self._ws.send(json.dumps({
            "type": "synthesize",
            "text": tagged_text,
            "emotion": self._current_emotion,
        }))

        t0 = time.monotonic()
        first_chunk = True

        # Receive audio chunks until end-of-utterance signal
        async for message in self._ws:
            if isinstance(message, bytes):
                if first_chunk:
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    logger.info("Silk WS TTS: first_chunk=%dms", latency_ms)
                    first_chunk = False

                # Convert to mulaw 8kHz
                if self._sample_rate == 24000:
                    yield pcm24k_to_mulaw8k(message)
                elif self._sample_rate == 16000:
                    yield pcm16k_to_mulaw8k(message)
                else:
                    import audioop
                    yield audioop.lin2ulaw(message, 2)

            elif isinstance(message, str):
                data = json.loads(message)
                if data.get("type") == "end":
                    break
                elif data.get("type") == "error":
                    logger.error("Silk WS error: %s", data.get("message"))
                    break
