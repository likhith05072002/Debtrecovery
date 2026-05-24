"""
Rumik Silk TTS plugin for LiveKit Agents.

Discovered API surface (from silk-dashboard-api.rumik.ai):

Base URL: https://silk-dashboard-api.rumik.ai
Auth:     Bearer {rk_live_xxx} or Firebase ID token

Endpoints:
  GET  /api/v1/models                        → list models (muga, mulberry)
  POST /api/playground/tts                    → non-streaming TTS
  WSS  /api/v1/playground/tts/stream?token=X  → streaming TTS (WebSocket)

WebSocket protocol:
  → Client sends: JSON {text, model, voiceId, ...}
  ← Server sends: "ready" → "queued" → "started" → binary audio → "done"

Models:
  muga     — premium ($25/M chars), highest quality
  mulberry — standard ($10/M chars), good quality

Pressure → Emotion mapping (via Silk prompt engineering):
  Level 0 → neutral/warm
  Level 1-2 → firm
  Level 3 → stern
  Level 4 → urgent
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx
import numpy as np

from livekit.agents import tts, utils

logger = logging.getLogger(__name__)

SILK_API_BASE = "https://silk-dashboard-api.rumik.ai"
SILK_WS_BASE = "wss://silk-dashboard-api.rumik.ai"

PRESSURE_TO_STYLE = {
    0: "neutral, professional, calm",
    1: "firm, confident, direct",
    2: "assertive, serious, no-nonsense",
    3: "stern, authoritative, pressing",
    4: "urgent, last-chance, final warning",
}

DEESCALATION_STYLE = "empathetic, warm, encouraging, relieved"


class SilkTTS(tts.TTS):
    """Custom LiveKit TTS plugin for Rumik Silk.

    Usage:
        silk = SilkTTS(api_key="rk_live_...", model="muga")
        session = AgentSession(tts=silk, ...)
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "muga",
        voice_id: str | None = None,
        sample_rate: int = 24000,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._api_key = api_key
        self._model = model
        self._voice_id = voice_id
        self._sample_rate = sample_rate
        self._style_prompt: str = PRESSURE_TO_STYLE[0]

    def set_pressure_level(self, level: int) -> None:
        """Set voice style based on pressure escalation level (0-4)."""
        self._style_prompt = PRESSURE_TO_STYLE.get(level, PRESSURE_TO_STYLE[0])

    def set_deescalation(self) -> None:
        """Switch to empathetic tone for payment intent de-escalation."""
        self._style_prompt = DEESCALATION_STYLE

    def set_style(self, style: str) -> None:
        """Set arbitrary style prompt."""
        self._style_prompt = style

    def synthesize(self, text: str, *, conn_options: tts.APIConnectOptions | None = None) -> "SilkChunkedStream":
        return SilkChunkedStream(tts=self, text=text, conn_options=conn_options)

    def stream(self) -> "SilkSynthesizeStream":
        return SilkSynthesizeStream(tts=self)


class SilkChunkedStream(tts.ChunkedStream):
    """Non-streaming TTS via HTTP POST."""

    def __init__(self, *, tts: SilkTTS, text: str, conn_options: tts.APIConnectOptions | None) -> None:
        super().__init__(tts=tts, input_text=text, conn_options=conn_options)
        self._silk = tts

    async def _run(self) -> None:
        headers = {
            "Authorization": f"Bearer {self._silk._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "text": self.input_text,
            "model": self._silk._model,
        }
        if self._silk._voice_id:
            payload["voiceId"] = self._silk._voice_id

        request_id = utils.shortuuid()
        t0 = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", f"{SILK_API_BASE}/api/playground/tts",
                                          json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise Exception(f"Silk HTTP {response.status_code}: {body[:200]}")

                    first = True
                    async for raw_chunk in response.aiter_bytes(4096):
                        if first:
                            logger.info("Silk TTFB: %.0fms model=%s",
                                        (time.monotonic() - t0) * 1000, self._silk._model)
                            first = False

                        samples = np.frombuffer(raw_chunk, dtype=np.int16)
                        if len(samples) == 0:
                            continue

                        frame = tts.AudioFrame(
                            data=samples.tobytes(),
                            sample_rate=self._silk._sample_rate,
                            num_channels=1,
                            samples_per_channel=len(samples),
                        )
                        self._event_ch.send_nowait(
                            tts.SynthesizedAudio(request_id=request_id, frame=frame)
                        )

        except Exception as exc:
            logger.error("Silk TTS error: %s", exc)
            raise


class SilkSynthesizeStream(tts.SynthesizeStream):
    """Streaming TTS via WebSocket — lowest latency path.

    WebSocket protocol:
      Connect: wss://silk-dashboard-api.rumik.ai/api/v1/playground/tts/stream?token={api_key}
      Send:    JSON {text, model, voiceId}
      Receive: JSON "ready" → JSON "started" → binary audio chunks → JSON "done"
    """

    def __init__(self, *, tts: SilkTTS) -> None:
        super().__init__(tts=tts)
        self._silk = tts

    async def _run(self) -> None:
        import websockets

        ws_url = f"{SILK_WS_BASE}/api/v1/playground/tts/stream?token={self._silk._api_key}"

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10,
                max_size=2**20,
            ) as ws:
                # Process text inputs from the pipeline
                async for text_input in self._input_ch:
                    if not isinstance(text_input, str) or not text_input.strip():
                        continue

                    request_id = utils.shortuuid()
                    t0 = time.monotonic()

                    # Send synthesis request
                    msg = {
                        "text": text_input.strip(),
                        "model": self._silk._model,
                    }
                    if self._silk._voice_id:
                        msg["voiceId"] = self._silk._voice_id

                    await ws.send(json.dumps(msg))

                    # Receive audio chunks until "done"
                    first_audio = True
                    async for message in ws:
                        if isinstance(message, bytes):
                            # Binary = PCM audio data
                            if first_audio:
                                logger.info("Silk WS TTFB: %.0fms",
                                            (time.monotonic() - t0) * 1000)
                                first_audio = False

                            samples = np.frombuffer(message, dtype=np.int16)
                            if len(samples) == 0:
                                continue

                            frame = tts.AudioFrame(
                                data=samples.tobytes(),
                                sample_rate=self._silk._sample_rate,
                                num_channels=1,
                                samples_per_channel=len(samples),
                            )
                            self._event_ch.send_nowait(
                                tts.SynthesizedAudio(request_id=request_id, frame=frame)
                            )

                        elif isinstance(message, str):
                            data = json.loads(message)
                            msg_type = data.get("type", data.get("status", ""))

                            if msg_type == "done":
                                break
                            elif msg_type == "error":
                                logger.error("Silk WS error: %s", data.get("message"))
                                break
                            elif msg_type in ("ready", "queued", "started"):
                                continue
                            else:
                                logger.debug("Silk WS unknown message: %s", data)

        except Exception as exc:
            logger.error("Silk WebSocket error: %s", exc)
            raise
