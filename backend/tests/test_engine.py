"""
test_engine.py
--------------
Unit tests for _extract_json in backend/src/core/engine.py.

_extract_json is critical — a bug here causes the entire AI pipeline to fail
silently, so we test every format Claude might return.
Run with:  pytest backend/tests/test_engine.py -v
"""

import json
import pytest
from backend.src.core.engine import _extract_json


# ---------------------------------------------------------------------------
# Happy-path: valid formats Claude might return
# ---------------------------------------------------------------------------
class TestExtractJsonHappyPath:
    def test_raw_json_array(self):
        raw = '[{"ticker": "BTC", "action": "LONG"}]'
        result = _extract_json(raw)
        assert isinstance(result, list)
        assert result[0]["ticker"] == "BTC"

    def test_raw_json_object(self):
        raw = '{"ticker": "ETH", "action": "HOLD"}'
        result = _extract_json(raw)
        assert isinstance(result, dict)
        assert result["action"] == "HOLD"

    def test_markdown_fence_json(self):
        raw = '```json\n[{"ticker": "SOL", "action": "SHORT"}]\n```'
        result = _extract_json(raw)
        assert result[0]["ticker"] == "SOL"

    def test_markdown_fence_no_lang(self):
        raw = '```\n[{"ticker": "DOGE", "action": "HOLD"}]\n```'
        result = _extract_json(raw)
        assert result[0]["ticker"] == "DOGE"

    def test_json_with_preamble(self):
        """Claude often says 'Here is my analysis:' before the JSON."""
        raw = 'Here is my analysis:\n\n[{"ticker": "BTC", "action": "LONG", "confidence": 80}]'
        result = _extract_json(raw)
        assert result[0]["confidence"] == 80

    def test_json_with_postamble(self):
        raw = '[{"ticker": "ETH", "action": "SHORT"}]\n\nHope this helps!'
        result = _extract_json(raw)
        assert result[0]["action"] == "SHORT"

    def test_json_with_preamble_and_postamble(self):
        raw = 'Analysis done.\n[{"ticker": "XRP", "action": "HOLD"}]\nLet me know!'
        result = _extract_json(raw)
        assert result[0]["ticker"] == "XRP"

    def test_multi_item_array(self):
        data = [
            {"ticker": "BTC", "action": "LONG", "confidence": 85},
            {"ticker": "ETH", "action": "HOLD", "confidence": 45},
            {"ticker": "SOL", "action": "SHORT", "confidence": 72},
        ]
        raw = json.dumps(data)
        result = _extract_json(raw)
        assert len(result) == 3
        assert result[2]["ticker"] == "SOL"

    def test_nested_json_object(self):
        """Objects with nested dicts should parse cleanly."""
        raw = '{"ticker": "BTC", "data": {"rsi": 72, "ema": 50000}}'
        result = _extract_json(raw)
        assert result["data"]["rsi"] == 72

    def test_whitespace_padded(self):
        raw = '   \n\n  [{"ticker": "BTC", "action": "LONG"}]  \n\n  '
        result = _extract_json(raw)
        assert result[0]["ticker"] == "BTC"

    def test_fence_with_extra_whitespace(self):
        raw = '```json\n\n  [{"ticker": "ETH"}]  \n\n```'
        result = _extract_json(raw)
        assert result[0]["ticker"] == "ETH"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestExtractJsonEdgeCases:
    def test_empty_array(self):
        raw = '[]'
        result = _extract_json(raw)
        assert result == []

    def test_empty_object(self):
        raw = '{}'
        result = _extract_json(raw)
        assert result == {}

    def test_integer_confidence_preserved(self):
        raw = '[{"confidence": 90, "action": "LONG"}]'
        result = _extract_json(raw)
        assert result[0]["confidence"] == 90

    def test_float_values_preserved(self):
        raw = '[{"suggested_sl": 48500.75, "suggested_tp": 52000.50}]'
        result = _extract_json(raw)
        assert result[0]["suggested_sl"] == pytest.approx(48500.75)

    def test_unicode_in_strings(self):
        """Reasoning strings often contain unicode characters."""
        raw = '[{"reasoning": "Бычий тренд на BTC 🚀"}]'
        result = _extract_json(raw)
        assert "Бычий" in result[0]["reasoning"]


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------
class TestExtractJsonFailures:
    def test_raises_on_plain_text(self):
        with pytest.raises(ValueError):
            _extract_json("I cannot provide a recommendation at this time.")

    def test_raises_on_empty_string(self):
        with pytest.raises((ValueError, Exception)):
            _extract_json("")

    def test_raises_on_broken_json(self):
        with pytest.raises((ValueError, Exception)):
            _extract_json('[{"ticker": "BTC", "action":}]')  # invalid JSON
