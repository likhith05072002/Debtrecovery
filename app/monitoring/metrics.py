"""Prometheus metrics definitions and FastAPI integration."""
from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

# ── Call metrics ──────────────────────────────────────────────────────────────
calls_initiated = Counter("calls_initiated_total", "Total outbound calls initiated")
calls_connected = Counter("calls_connected_total", "Total calls answered by borrower")
calls_completed = Counter("calls_completed_total", "Total calls that ended with any outcome", ["outcome"])
compliance_violations = Counter("compliance_violations_total", "FDCPA compliance violations detected", ["type"])
promises_made = Counter("promises_made_total", "Repayment promises recorded during calls")

# ── Latency histograms ────────────────────────────────────────────────────────
stt_latency = Histogram(
    "stt_latency_ms",
    "Deepgram STT latency from audio receipt to final transcript (ms)",
    buckets=[50, 100, 150, 200, 300, 500, 1000],
)
llm_latency = Histogram(
    "llm_latency_ms",
    "GPT-4o latency from transcript to first token (ms)",
    buckets=[100, 200, 350, 500, 750, 1000, 2000],
)
tts_latency = Histogram(
    "tts_latency_ms",
    "ElevenLabs TTS latency from text to first audio chunk (ms)",
    buckets=[50, 80, 120, 200, 350, 500],
)
e2e_latency = Histogram(
    "e2e_response_latency_ms",
    "End-to-end response latency: STT final → borrower hears audio (ms)",
    buckets=[300, 500, 700, 1000, 1500, 2000],
)

# ── Barge-in metrics ─────────────────────────────────────────────────────────
barge_in_triggered = Counter(
    "barge_in_triggered_total",
    "Total barge-in events by detection path",
    ["path"],   # "audio_level" | "interim_transcript"
)
barge_in_false_positive = Counter(
    "barge_in_false_positive_total",
    "Barge-ins where Deepgram produced no final transcript (likely false positive)",
)
barge_in_latency = Histogram(
    "barge_in_interrupt_latency_ms",
    "Time from barge-in detection to Twilio buffer clear (ms)",
    buckets=[10, 20, 40, 60, 100, 150, 200],
)

# ── Turn detection metrics ───────────────────────────────────────────────────
turn_decisions = Counter(
    "turn_detection_decisions_total",
    "Turn detector decisions by outcome",
    ["decision", "reason"],   # decision: "complete" | "incomplete"
)
turn_wait_abandoned = Counter(
    "turn_wait_abandoned_total",
    "Times we waited for continuation but borrower went silent (wasted wait)",
)

# ── VAD metrics ──────────────────────────────────────────────────────────────
vad_speech_prob = Histogram(
    "vad_speech_probability",
    "Silero VAD speech probability distribution during agent speaking",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
vad_backend = Counter(
    "vad_backend_used_total",
    "Which VAD backend was used",
    ["backend"],   # "silero" | "energy_zcr"
)

# ── AEC metrics ──────────────────────────────────────────────────────────────
aec_echo_detected = Counter(
    "aec_echo_detected_total",
    "Frames where echo correlation > 0.3 (echo was present and subtracted)",
)
aec_echo_gain = Histogram(
    "aec_echo_gain",
    "Echo attenuation factor distribution (0=no echo, 0.95=strong echo)",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
)

# ── Fast-first-sentence metrics ──────────────────────────────────────────────
fast_first_wins = Counter(
    "fast_first_sentence_wins_total",
    "Times the fast model delivered first sentence before main model",
)
fast_first_skipped = Counter(
    "fast_first_sentence_skipped_total",
    "Times fast model was skipped",
    ["reason"],   # "question" | "compliance" | "barge_in" | "pressure" | "payment_intent"
)
fast_first_ttft = Histogram(
    "fast_first_sentence_ttft_ms",
    "Time to first token from fast model (ms)",
    buckets=[50, 100, 150, 200, 300, 500, 800],
)
main_model_ttft = Histogram(
    "main_model_ttft_ms",
    "Time to first sentence from main model (ms)",
    buckets=[200, 350, 500, 700, 1000, 1500],
)

# ── Active sessions ───────────────────────────────────────────────────────────
active_calls = Gauge("active_calls", "Number of currently active WebSocket call sessions")


def setup_metrics(app: FastAPI) -> None:
    """Mount Prometheus metrics endpoint at /metrics."""
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
