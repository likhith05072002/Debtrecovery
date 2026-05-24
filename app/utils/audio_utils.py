"""
Audio format conversion utilities for the Twilio <-> STT/TTS pipeline.

Twilio Media Streams sends/receives mulaw 8kHz (G.711 µ-law).
Deepgram expects linear PCM 16-bit 8kHz or 16kHz.
ElevenLabs returns PCM 24kHz.

All conversion is done in-process using audioop (stdlib) + numpy for speed.
"""
from __future__ import annotations

import audioop
import base64
import struct
from typing import Iterator


# ── Mulaw / PCM conversion ────────────────────────────────────────────────────

def mulaw_to_pcm16(mulaw_bytes: bytes, *, sample_rate: int = 8000) -> bytes:
    """Convert G.711 µ-law to 16-bit signed PCM (same sample rate)."""
    return audioop.ulaw2lin(mulaw_bytes, 2)


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit signed PCM to G.711 µ-law."""
    return audioop.lin2ulaw(pcm_bytes, 2)


def resample_pcm16(pcm_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample 16-bit PCM to a different sample rate using audioop.ratecv."""
    if src_rate == dst_rate:
        return pcm_bytes
    converted, _ = audioop.ratecv(pcm_bytes, 2, 1, src_rate, dst_rate, None)
    return converted


def pcm24k_to_mulaw8k(pcm_bytes: bytes) -> bytes:
    """Convert ElevenLabs PCM 24kHz output → Twilio mulaw 8kHz."""
    pcm_8k = resample_pcm16(pcm_bytes, 24000, 8000)
    return pcm16_to_mulaw(pcm_8k)


def pcm16k_to_mulaw8k(pcm_bytes: bytes) -> bytes:
    """Convert 16kHz PCM → Twilio mulaw 8kHz."""
    pcm_8k = resample_pcm16(pcm_bytes, 16000, 8000)
    return pcm16_to_mulaw(pcm_8k)


# ── Twilio Media Stream helpers ───────────────────────────────────────────────

def decode_twilio_payload(payload: str) -> bytes:
    """Decode base64 Twilio Media Stream audio payload to raw mulaw bytes."""
    return base64.b64decode(payload)


def encode_twilio_payload(mulaw_bytes: bytes) -> str:
    """Encode raw mulaw bytes as base64 string for Twilio Media Stream send."""
    return base64.b64encode(mulaw_bytes).decode("utf-8")


# ── Energy / VAD helpers ──────────────────────────────────────────────────────

def rms_energy(pcm_bytes: bytes) -> float:
    """Compute root-mean-square energy of a 16-bit PCM buffer (0–32767 scale)."""
    if not pcm_bytes:
        return 0.0
    return audioop.rms(pcm_bytes, 2)


def is_speech(pcm_bytes: bytes, threshold: int = 300) -> bool:
    """Energy-based voice activity detection with optional zero-crossing check."""
    return rms_energy(pcm_bytes) > threshold


def zero_crossing_rate(pcm_bytes: bytes) -> float:
    """Compute zero-crossing rate of 16-bit PCM audio.

    Speech typically has ZCR of 0.02-0.40.
    White noise has ZCR ~0.50.
    Low-frequency hum has ZCR < 0.01.
    """
    if len(pcm_bytes) < 4:
        return 0.0
    n_samples = len(pcm_bytes) // 2
    if n_samples < 2:
        return 0.0
    samples = struct.unpack(f"<{n_samples}h", pcm_bytes[:n_samples * 2])
    crossings = sum(
        1 for i in range(1, len(samples))
        if (samples[i] >= 0) != (samples[i - 1] >= 0)
    )
    return crossings / (n_samples - 1)


# ── Chunk iterator ────────────────────────────────────────────────────────────

def chunk_audio(audio_bytes: bytes, chunk_size_bytes: int = 320) -> Iterator[bytes]:
    """Yield fixed-size chunks from a raw audio buffer."""
    for i in range(0, len(audio_bytes), chunk_size_bytes):
        chunk = audio_bytes[i : i + chunk_size_bytes]
        if chunk:
            yield chunk
