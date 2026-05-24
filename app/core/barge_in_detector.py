"""
Barge-in (interruption) detector with Silero VAD + adaptive noise floor.

Frontier-level barge-in detection:
- Silero VAD (neural network, <1ms on CPU) replaces ZCR/RMS heuristics
- Adaptive noise floor calibration per call
- Smoothed probability tracking prevents single-frame false positives
- Consecutive-frame requirement for confirmation
- Single instance shared between media_stream and orchestrator
"""
from __future__ import annotations

import logging
import struct
import time
from collections import deque
from typing import Optional

import numpy as np

from app.utils.audio_utils import rms_energy

logger = logging.getLogger(__name__)

# ── Silero VAD singleton ─────────────────────────────────────────────────────

_silero_model = None
_silero_utils = None


def _get_silero_vad():
    """Lazy-load Silero VAD model (downloads on first use, ~1MB)."""
    global _silero_model, _silero_utils
    if _silero_model is not None:
        return _silero_model, _silero_utils

    try:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        _silero_model = model
        _silero_utils = utils
        logger.info("Silero VAD model loaded successfully")
        return model, utils
    except Exception as exc:
        logger.warning("Silero VAD unavailable, falling back to energy-based detection: %s", exc)
        return None, None


class BargeInDetector:
    """
    Neural VAD barge-in detection with energy fallback.

    Primary: Silero VAD (neural network, trained on speech/noise discrimination)
    Fallback: RMS energy + adaptive noise floor (if torch unavailable)

    Triggers if:
    - Silero speech probability > 0.5 (smoothed) AND
    - Agent has been speaking for at least min_speaking_ms AND
    - Cooldown has elapsed since last barge-in AND
    - 2+ consecutive frames confirm speech
    """

    def __init__(
        self,
        energy_threshold: int = 350,
        min_speaking_ms: int = 120,       # conservative until AEC is measured on real calls
        cooldown_ms: int = 400,
        silero_threshold: float = 0.5,    # Silero speech probability threshold
        noise_floor_window: int = 50,
        energy_headroom_db: float = 12.0,
        smoothing_alpha: float = 0.35,
    ) -> None:
        self._static_threshold = energy_threshold
        self._min_speaking_ms = min_speaking_ms
        self._cooldown_ms = cooldown_ms
        self._silero_threshold = silero_threshold
        self._noise_floor_window = noise_floor_window
        self._energy_headroom_db = energy_headroom_db
        self._smoothing_alpha = smoothing_alpha

        # Load Silero VAD
        self._silero_model, self._silero_utils = _get_silero_vad()
        self._use_silero = self._silero_model is not None

        # State
        self._agent_speaking_since: float | None = None
        self._last_barge_in: float = 0.0

        # Adaptive noise floor
        self._noise_samples: deque[float] = deque(maxlen=noise_floor_window)
        self._noise_floor: float = 0.0
        self._calibrated: bool = False
        self._calibration_frames: int = 0

        # Smoothed speech probability (Silero) or energy (fallback)
        self._smoothed_speech_prob: float = 0.0
        self._smoothed_energy: float = 0.0

        # Consecutive speech frames
        self._consecutive_speech_frames: int = 0
        self._speech_frame_threshold: int = 2

        # Silero internal state (must be reset between utterances)
        self._silero_state = None
        if self._use_silero:
            self._reset_silero_state()

        # Interim dedup
        self._last_interim_text: str = ""

        # AEC reference buffer (agent's outgoing audio for echo subtraction)
        self._echo_ref_buffer: deque[bytes] = deque(maxlen=25)  # ~500ms at 20ms/frame
        self._aec_enabled: bool = False

    def _reset_silero_state(self) -> None:
        """Reset Silero's internal RNN state."""
        if self._silero_model is not None:
            import torch
            self._silero_state = torch.zeros(2, 1, 128)

    def enable_aec(self) -> None:
        """Enable acoustic echo cancellation."""
        self._aec_enabled = True

    def feed_echo_reference(self, outgoing_pcm: bytes) -> None:
        """Feed agent's outgoing audio for echo reference (AEC).

        Called when TTS audio is sent to Twilio. The same audio will
        arrive back ~100-300ms later via the borrower's mic.
        """
        if self._aec_enabled:
            self._echo_ref_buffer.append(outgoing_pcm)

    def _subtract_echo(self, pcm_bytes: bytes) -> bytes:
        """Simple spectral subtraction echo cancellation.

        Subtracts estimated echo energy from the incoming signal.
        Not as good as WebRTC AEC3, but significantly reduces false positives
        from agent echo on speakerphone / cheap handsets.
        """
        if not self._aec_enabled or not self._echo_ref_buffer:
            return pcm_bytes

        # Use the oldest reference frame (closest to the expected echo delay)
        ref = self._echo_ref_buffer[0]

        n_samples = min(len(pcm_bytes), len(ref)) // 2
        if n_samples < 2:
            return pcm_bytes

        # Convert to numpy arrays
        incoming = np.frombuffer(pcm_bytes[:n_samples * 2], dtype=np.int16).astype(np.float32)
        reference = np.frombuffer(ref[:n_samples * 2], dtype=np.int16).astype(np.float32)

        # Estimate echo level (normalized cross-correlation)
        ref_energy = np.dot(reference, reference)
        if ref_energy < 1.0:
            return pcm_bytes

        # Compute echo attenuation factor
        correlation = np.dot(incoming, reference) / ref_energy
        echo_gain = max(0.0, min(correlation, 0.95))  # cap at 0.95 to preserve signal

        # Instrument echo levels
        try:
            from app.monitoring.metrics import aec_echo_detected, aec_echo_gain
            if echo_gain > 0.3:
                aec_echo_detected.inc()
            aec_echo_gain.observe(echo_gain)
        except ImportError:
            pass

        # Subtract estimated echo
        cleaned = incoming - echo_gain * reference
        cleaned = np.clip(cleaned, -32768, 32767).astype(np.int16)

        return cleaned.tobytes()

    def agent_started_speaking(self) -> None:
        self._agent_speaking_since = time.monotonic()

    def agent_stopped_speaking(self) -> None:
        self._agent_speaking_since = None
        # Reset Silero state when agent stops — next borrower utterance is fresh
        if self._use_silero:
            self._reset_silero_state()

    @property
    def is_agent_speaking(self) -> bool:
        return self._agent_speaking_since is not None

    @property
    def adaptive_threshold(self) -> float:
        """Energy threshold — noise floor + headroom, or static fallback."""
        if self._calibrated and self._noise_floor > 0:
            import math
            multiplier = 10 ** (self._energy_headroom_db / 20)
            adaptive = self._noise_floor * multiplier
            return max(adaptive, self._static_threshold * 0.5)
        return self._static_threshold

    def calibrate(self, pcm_bytes: bytes) -> None:
        """Feed audio frames during call setup to estimate noise floor."""
        energy = rms_energy(pcm_bytes)
        self._noise_samples.append(energy)
        self._calibration_frames += 1

        if self._calibration_frames >= self._noise_floor_window:
            if self._noise_samples:
                sorted_samples = sorted(self._noise_samples)
                self._noise_floor = sorted_samples[len(sorted_samples) // 2]
                self._calibrated = True

    def _update_noise_floor(self, energy: float) -> None:
        """Continuously update noise floor when agent is NOT speaking."""
        if self._agent_speaking_since is None and energy < self._static_threshold:
            self._noise_samples.append(energy)
            if len(self._noise_samples) >= 10:
                sorted_samples = sorted(self._noise_samples)
                self._noise_floor = sorted_samples[len(sorted_samples) // 2]
                self._calibrated = True

    def _silero_speech_prob(self, pcm_bytes: bytes) -> float:
        """Run Silero VAD on a PCM chunk. Returns speech probability 0.0-1.0.

        Silero expects 16kHz input, but our audio is 8kHz.
        We use torchaudio.functional.resample with a proper anti-aliasing
        lowpass filter — NOT sample duplication, which creates spectral mirrors
        that fool fricative detection (s, sh, f sounds) on phone-codec audio.
        Silero processes 512 samples (32ms at 16kHz).
        """
        import torch
        import torchaudio.functional as F

        n_samples = len(pcm_bytes) // 2
        if n_samples < 64:
            return 0.0

        # Parse 16-bit PCM to float32 tensor, normalize to [-1, 1]
        samples = np.frombuffer(pcm_bytes[:n_samples * 2], dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples)

        # Proper resampling 8kHz → 16kHz with anti-aliasing filter
        # This avoids the aliasing artifacts that sample duplication introduces
        # in the fricative frequency band (4-8kHz after mirroring)
        upsampled = F.resample(tensor, orig_freq=8000, new_freq=16000)

        # Silero needs exactly 512 samples (32ms at 16kHz)
        if upsampled.shape[0] < 512:
            upsampled = torch.nn.functional.pad(upsampled, (0, 512 - upsampled.shape[0]))
        elif upsampled.shape[0] > 512:
            upsampled = upsampled[:512]

        # Run Silero VAD
        with torch.no_grad():
            speech_prob = self._silero_model(upsampled, 16000).item()

        return speech_prob

    def detect(self, pcm_bytes: bytes) -> bool:
        """
        Check if borrower audio justifies interrupting agent speech.
        Returns True if agent should be interrupted.

        Uses Silero VAD (neural) if available, falls back to energy+ZCR.
        """
        # Apply echo cancellation if enabled
        pcm_bytes = self._subtract_echo(pcm_bytes)

        energy = rms_energy(pcm_bytes)
        self._update_noise_floor(energy)

        if self._agent_speaking_since is None:
            self._consecutive_speech_frames = 0
            return False

        now = time.monotonic()

        # Cooldown
        if (now - self._last_barge_in) * 1000 < self._cooldown_ms:
            self._consecutive_speech_frames = 0
            return False

        # Min agent speaking time
        elapsed_ms = (now - self._agent_speaking_since) * 1000
        if elapsed_ms < self._min_speaking_ms:
            return False

        # ── Speech detection ─────────────────────────────────────────────────
        is_speech = False

        if self._use_silero:
            # Neural VAD path
            prob = self._silero_speech_prob(pcm_bytes)
            self._smoothed_speech_prob = (
                self._smoothing_alpha * prob
                + (1 - self._smoothing_alpha) * self._smoothed_speech_prob
            )

            # Instrument VAD probability distribution
            try:
                from app.monitoring.metrics import vad_speech_prob, vad_backend
                vad_speech_prob.observe(self._smoothed_speech_prob)
                if self._consecutive_speech_frames == 0:  # only count once per detection attempt
                    vad_backend.labels(backend="silero").inc()
            except ImportError:
                pass

            # Energy gate: even with high Silero prob, reject if energy is below
            # noise floor (prevents Silero false positives on quiet artifacts)
            energy_ok = energy > self.adaptive_threshold * 0.7
            is_speech = self._smoothed_speech_prob > self._silero_threshold and energy_ok

        else:
            # Fallback: energy + ZCR
            self._smoothed_energy = (
                self._smoothing_alpha * energy
                + (1 - self._smoothing_alpha) * self._smoothed_energy
            )

            if self._smoothed_energy > self.adaptive_threshold:
                zcr = _zero_crossing_rate(pcm_bytes)
                is_speech = 0.02 <= zcr <= 0.45

        if not is_speech:
            self._consecutive_speech_frames = 0
            return False

        # Consecutive frame confirmation
        self._consecutive_speech_frames += 1
        if self._consecutive_speech_frames < self._speech_frame_threshold:
            return False

        # Confirmed barge-in
        self._last_barge_in = now
        self._consecutive_speech_frames = 0
        return True

    def is_duplicate_interim(self, text: str) -> bool:
        """Check if an interim transcript is identical to the last one."""
        normalized = text.strip().lower()
        if normalized == self._last_interim_text:
            return True
        self._last_interim_text = normalized
        return False

    def reset_interim_dedup(self) -> None:
        """Reset interim dedup when a final transcript is processed."""
        self._last_interim_text = ""


def _zero_crossing_rate(pcm_bytes: bytes) -> float:
    """Compute zero-crossing rate of 16-bit PCM audio (fallback VAD)."""
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
