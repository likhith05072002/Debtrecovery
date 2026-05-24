"""
Rumik Silk TTS plugin for LiveKit Agents.

Custom LiveKit TTS provider wrapping Rumik Silk API.
Supports emotional mid-sentence tags for pressure-aware voice modulation.

Pressure → Emotion mapping:
    Level 0 → <neutral>/<warm>   (calm, professional)
    Level 1 → <firm>             (confident, direct)
    Level 2 → <firm>             (assertive, serious)
    Level 3 → <stern>            (authoritative)
    Level 4 → <urgent>           (pressing, last-chance)
    De-esc  → <empathetic>       (warm, encouraging)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
import numpy as np

from livekit.agents import tts, utils

logger = logging.getLogger(__name__)

SILK_API_URL = "https://api.rumik.ai/v1/tts/stream"

# Emotion tags Silk supports
PRESSURE_TO_EMOTION = {
    0: "neutral",
    1: "firm",
    2: "firm",
    3: "stern",
    4: "urgent",
}

SILK_VOICE_MAP = {
    "en": "silk-en-male-professional",
    "hi": "silk-hi-male-professional",
    "kn": "silk-kn-male-professional",
    "te": "silk-te-male-professional",
    "ta": "silk-ta-male-professional",
    "ml": "silk-ml-male-professional",
    "bn": "silk-bn-male-professional",
}


@dataclass
class SilkTTSOptions:
    api_key: str
    voice_id: str = "silk-en-male-professional"
    model_id: str = "silk-v1"
    language: str = "en"
    sample_rate: int = 24000
    emotion: str = "neutral"


class SilkTTS(tts.TTS):
    """Custom LiveKit TTS plugin for Rumik Silk.

    Usage with LiveKit AgentSession:
        silk = SilkTTS(
            api_key="sk_...",
            voice_id="silk-en-male-professional",
            language="en",
        )
        session = AgentSession(tts=silk, ...)
    """

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str | None = None,
        model_id: str = "silk-v1",
        language: str = "en",
        sample_rate: int = 24000,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._opts = SilkTTSOptions(
            api_key=api_key,
            voice_id=voice_id or SILK_VOICE_MAP.get(language, SILK_VOICE_MAP["en"]),
            model_id=model_id,
            language=language,
            sample_rate=sample_rate,
        )
        self._current_emotion = "neutral"

    def set_emotion(self, emotion: str) -> None:
        """Set emotion for next synthesis. Call before each turn based on pressure level."""
        self._current_emotion = emotion

    def set_pressure_level(self, level: int) -> None:
        """Set emotion based on pressure escalation level (0-4)."""
        self._current_emotion = PRESSURE_TO_EMOTION.get(level, "neutral")

    def synthesize(self, text: str, *, conn_options: tts.APIConnectOptions | None = None) -> "SilkChunkedStream":
        return SilkChunkedStream(tts=self, text=text, conn_options=conn_options)

    def stream(self) -> "SilkSynthesizeStream":
        return SilkSynthesizeStream(tts=self)


class SilkChunkedStream(tts.ChunkedStream):
    """Streams audio from a single Silk API call."""

    def __init__(self, *, tts: SilkTTS, text: str, conn_options: tts.APIConnectOptions | None) -> None:
        super().__init__(tts=tts, input_text=text, conn_options=conn_options)
        self._tts = tts

    async def _run(self) -> None:
        """Execute the Silk API call and emit audio frames."""
        opts = self._tts._opts
        emotion = self._tts._current_emotion

        # Inject emotion tag if not neutral
        tagged_text = self.input_text
        if emotion and emotion != "neutral":
            tagged_text = f"<{emotion}> {self.input_text}"

        headers = {
            "Authorization": f"Bearer {opts.api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        }
        payload = {
            "text": tagged_text,
            "voice_id": opts.voice_id,
            "model_id": opts.model_id,
            "language": opts.language,
            "sample_rate": opts.sample_rate,
            "output_format": "pcm_s16le",
            "emotion": emotion,
            "stream": True,
        }

        request_id = utils.shortuuid()
        t0 = time.monotonic()
        first_frame = True

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", SILK_API_URL, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.error("Silk API %d: %s", response.status_code, body[:300])
                        raise Exception(f"Silk API error: {response.status_code}")

                    async for raw_chunk in response.aiter_bytes(4096):
                        if first_frame:
                            ttfb = time.monotonic() - t0
                            logger.info("Silk TTFB: %.0fms voice=%s emotion=%s",
                                        ttfb * 1000, opts.voice_id, emotion)
                            first_frame = False

                        # Convert raw PCM bytes to LiveKit AudioFrame
                        samples = np.frombuffer(raw_chunk, dtype=np.int16)
                        frame = tts.AudioFrame(
                            data=samples.tobytes(),
                            sample_rate=opts.sample_rate,
                            num_channels=1,
                            samples_per_channel=len(samples),
                        )

                        self._event_ch.send_nowait(
                            tts.SynthesizedAudio(
                                request_id=request_id,
                                frame=frame,
                            )
                        )

        except httpx.TimeoutException:
            logger.error("Silk API timeout for text: %.40s", self.input_text)
            raise
        except Exception as exc:
            logger.error("Silk streaming error: %s", exc)
            raise


class SilkSynthesizeStream(tts.SynthesizeStream):
    """Streaming TTS — accepts text chunks, emits audio frames continuously."""

    def __init__(self, *, tts: SilkTTS) -> None:
        super().__init__(tts=tts)
        self._tts = tts

    async def _run(self) -> None:
        """Process text chunks from the input stream and synthesize audio."""
        async for text_input in self._input_ch:
            if isinstance(text_input, str) and text_input.strip():
                # Synthesize each text chunk individually
                stream = self._tts.synthesize(text_input)
                async for event in stream:
                    self._event_ch.send_nowait(event)
