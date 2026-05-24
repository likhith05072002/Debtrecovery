"""Unit tests for sentiment analysis."""
from app.services.profiling.sentiment_analyzer import analyze_sentiment, extract_entities


def test_positive_sentiment():
    result = analyze_sentiment("Yes okay, I can do that. I understand and I agree.")
    assert result.score > 0
    assert result.label in ("positive", "cooperative")


def test_negative_sentiment():
    result = analyze_sentiment("No I can't pay. This is ridiculous and not fair.")
    assert result.score < 0


def test_hostile_detection():
    result = analyze_sentiment("This is harassment and fraud. I'll sue you.")
    assert result.hostile_detected or result.label in ("hostile", "negative")


def test_hardship_detection():
    result = analyze_sentiment("I lost my job two months ago. I'm struggling.")
    assert result.hardship_detected


def test_entity_extraction_amounts():
    entities = extract_entities("I can pay ₹250 next month.")
    assert len(entities["amounts"]) > 0


def test_entity_extraction_dates():
    entities = extract_entities("I'll pay on April 15th.")
    assert len(entities["dates"]) > 0
