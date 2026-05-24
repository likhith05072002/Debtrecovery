"""
ElevenLabs streaming TTS client (eleven_turbo_v2).
Streams PCM audio chunks and converts to mulaw 8kHz for Twilio.
Falls back to Microsoft Edge TTS (free) if ElevenLabs returns 402.
Includes in-process cache for pre-warmed utterances (eliminates opening latency).
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
from app.utils.audio_utils import pcm24k_to_mulaw8k, chunk_audio

logger = logging.getLogger(__name__)

ELEVENLABS_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
EDGE_TTS_VOICE = "en-IN-PrabhatNeural"   # default Indian male English voice

LANGUAGE_TO_EDGE_VOICE = {
    "en": "en-IN-PrabhatNeural",
    "hi": "hi-IN-MadhurNeural",
    "kn": "kn-IN-GaganNeural",
    "te": "te-IN-MohanNeural",
}

# All languages use ElevenLabs — LLM always outputs Roman/English transliteration,
# so the voice can pronounce any language phonetically.
_ELEVENLABS_SUPPORTED = {"en", "hi", "kn", "te"}

# In-process cache: text → list of mulaw chunks (pre-warmed utterances play instantly)
_tts_cache: dict[str, list[bytes]] = {}


async def _synthesize_edge_tts(text: str, language: str = "en") -> AsyncGenerator[bytes, None]:
    """
    Fallback TTS using Microsoft Edge TTS (free, no API key).
    Collects MP3, converts to mulaw 8kHz via pydub, yields in 320-byte chunks.
    """
    import edge_tts
    from pydub import AudioSegment

    voice = LANGUAGE_TO_EDGE_VOICE.get(language, EDGE_TTS_VOICE)
    communicate = edge_tts.Communicate(text, voice=voice, rate="-5%")
    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])

    mp3_buffer.seek(0)
    audio = AudioSegment.from_mp3(mp3_buffer)
    audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)
    pcm_bytes = audio.raw_data

    import audioop
    mulaw_bytes = audioop.lin2ulaw(pcm_bytes, 2)
    for c in chunk_audio(mulaw_bytes, 320):
        yield c


class ElevenLabsTTSClient(TTSProvider):
    """
    Streams synthesized speech for a single sentence, yielding mulaw 8kHz
    audio chunks suitable for direct transmission via Twilio Media Streams.
    Falls back to Microsoft Edge TTS when ElevenLabs quota is exceeded (402).
    """

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    def __init__(self, language: str = "en") -> None:
        settings = get_settings()
        self._api_key = settings.elevenlabs_api_key
        self._voice_id = settings.elevenlabs_voice_id
        self._model_id = settings.elevenlabs_model_id
        self._stability = settings.elevenlabs_stability
        self._similarity_boost = settings.elevenlabs_similarity_boost
        self._language = language

    async def pre_warm(self, text: str) -> None:
        """
        Pre-generate TTS audio and cache it so the first utterance plays instantly.
        Call this during call setup (while Deepgram connects) so the opening
        greeting has zero TTS latency.
        """
        if text in _tts_cache:
            return
        chunks: list[bytes] = []
        async for chunk in self._generate(text):
            chunks.append(chunk)
        _tts_cache[text] = chunks
        logger.debug("TTS pre-warm complete for: %.40s", text)

    async def synthesize_stream(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream synthesized speech for `text`.
        Serves from cache if pre_warm() was called. Falls back to Edge TTS on 402.
        """
        if text in _tts_cache:
            logger.debug("TTS cache hit: %.40s", text)
            for chunk in _tts_cache[text]:
                yield chunk
                await asyncio.sleep(0)   # yield to event loop so callers can check stop conditions
            return

        async for chunk in self._generate(text, chunk_size=chunk_size):
            yield chunk

    async def _generate(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Internal: call ElevenLabs (or Edge TTS as fallback on API error), yield mulaw chunks."""
        if self._language not in _ELEVENLABS_SUPPORTED:
            async for chunk in _synthesize_edge_tts(text, self._language):
                yield chunk
            return

        url = ELEVENLABS_STREAM_URL.format(voice_id=self._voice_id) + "?output_format=pcm_24000"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        t0 = time.monotonic()
        first_chunk = True
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.error("ElevenLabs %d (voice=%s model=%s) body=%s — falling back to Edge TTS",
                                     response.status_code, self._voice_id, self._model_id, body[:300])
                        async for mulaw_chunk in _synthesize_edge_tts(text, self._language):
                            yield mulaw_chunk
                        return
                    async for raw_chunk in response.aiter_bytes(chunk_size):
                        if first_chunk:
                            latency_ms = int((time.monotonic() - t0) * 1000)
                            logger.info("ElevenLabs TTS active: voice=%s, first_chunk=%dms",
                                        self._voice_id, latency_ms)
                            first_chunk = False
                        mulaw_chunk = pcm24k_to_mulaw8k(raw_chunk)
                        yield mulaw_chunk
        except httpx.HTTPStatusError as exc:
            logger.error("ElevenLabs API error %d: %s", exc.response.status_code, exc.response.text)
            raise
        except Exception as exc:
            logger.error("ElevenLabs streaming error: %s", exc)
            raise
