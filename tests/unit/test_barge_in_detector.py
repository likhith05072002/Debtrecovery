"""Unit tests for barge-in detector."""
import time
from app.core.barge_in_detector import BargeInDetector


def test_no_barge_in_when_agent_not_speaking():
    detector = BargeInDetector()
    # Generate a large audio buffer with high energy
    pcm_bytes = bytes([127] * 1000)
    assert not detector.detect(pcm_bytes)


def test_no_barge_in_before_min_duration():
    detector = BargeInDetector(energy_threshold=10, min_speaking_ms=500)
    detector.agent_started_speaking()
    # Only 100ms has passed — below min_speaking_ms of 500ms
    pcm_bytes = bytes([200] * 2000)
    assert not detector.detect(pcm_bytes)


def test_barge_in_detected_after_min_duration():
    detector = BargeInDetector(energy_threshold=10, min_speaking_ms=0, cooldown_ms=0)
    detector.agent_started_speaking()
    pcm_bytes = bytes([200] * 2000)
    assert detector.detect(pcm_bytes)


def test_cooldown_prevents_double_trigger():
    detector = BargeInDetector(energy_threshold=10, min_speaking_ms=0, cooldown_ms=5000)
    detector.agent_started_speaking()
    pcm_bytes = bytes([200] * 2000)
    assert detector.detect(pcm_bytes)
    assert not detector.detect(pcm_bytes)  # Cooldown active
