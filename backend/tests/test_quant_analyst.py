"""
test_quant_analyst.py
---------------------
Unit tests for backend/src/core/agents/quant_analyst.py.

Pure JSON-parsing functions are tested directly.
The Anthropic API client is fully mocked.
Run with:  pytest backend/tests/test_quant_analyst.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.core.agents.quant_analyst import (
    _extract_json_quant,
    propose_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anthropic_response(content: str):
    """Build a fake Anthropic messages.create() response."""
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def _ticker_data(ticker="BTC"):
    return {"ticker": ticker, "condensed": f"{ticker} 4H: RSI=55, EMA trend: UP"}


# ---------------------------------------------------------------------------
# _extract_json_quant — pure function
# ---------------------------------------------------------------------------

class TestExtractJsonQuant:

    def test_raw_json_array(self):
        raw = '[{"ticker": "BTC", "proposed_action": "LONG", "confidence": 80}]'
        result = _extract_json_quant(raw)
        assert isinstance(result, list)
        assert result[0]["ticker"] == "BTC"

    def test_markdown_fenced_json(self):
        data = [{"ticker": "ETH", "proposed_action": "LONG", "confidence": 75}]
        raw = f"```json\n{json.dumps(data)}\n```"
        result = _extract_json_quant(raw)
        assert result[0]["ticker"] == "ETH"

    def test_markdown_fence_no_lang(self):
        data = [{"ticker": "SOL", "proposed_action": "SHORT", "confidence": 65}]
        raw = f"```\n{json.dumps(data)}\n```"
        result = _extract_json_quant(raw)
        assert result[0]["proposed_action"] == "SHORT"

    def test_preamble_before_array(self):
        data = [{"ticker": "ADA", "proposed_action": "LONG", "confidence": 70}]
        raw = f"Here is my analysis:\n\n{json.dumps(data)}"
        result = _extract_json_quant(raw)
        assert result[0]["ticker"] == "ADA"

    def test_multi_ticker_array(self):
        data = [
            {"ticker": "BTC", "proposed_action": "LONG", "confidence": 85},
            {"ticker": "ETH", "proposed_action": "HOLD", "confidence": 40},
        ]
        result = _extract_json_quant(json.dumps(data))
        assert len(result) == 2

    def test_single_object_wrapped_in_list(self):
        raw = '{"ticker": "BNB", "proposed_action": "LONG", "confidence": 72}'
        result = _extract_json_quant(raw)
        assert isinstance(result, list)
        assert result[0]["ticker"] == "BNB"

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError):
            _extract_json_quant("I cannot provide advice right now.")

    def test_empty_string_raises(self):
        with pytest.raises((ValueError, Exception)):
            _extract_json_quant("")

    def test_broken_json_raises(self):
        with pytest.raises((ValueError, Exception)):
            _extract_json_quant('[{"ticker": "BTC", "action":}]')

    def test_unicode_in_reasoning(self):
        data = [{"ticker": "BTC", "quant_reasoning": "Бычий тренд 🚀", "confidence": 80}]
        result = _extract_json_quant(json.dumps(data))
        assert "Бычий" in result[0]["quant_reasoning"]

    def test_float_values_preserved(self):
        data = [{"suggested_sl": 48500.75, "suggested_tp": 52000.50}]
        result = _extract_json_quant(json.dumps(data))
        assert result[0]["suggested_sl"] == pytest.approx(48500.75)


# ---------------------------------------------------------------------------
# propose_trades — async, mock Anthropic
# ---------------------------------------------------------------------------

class TestProposeTrades:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self, monkeypatch):
        """Without an API key, returns empty list immediately."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "")
        result = await propose_trades([_ticker_data()], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_long_above_threshold_returned(self, monkeypatch):
        """Proposal with LONG and confidence ≥ threshold → included."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(mod, "CONFIDENCE_THRESHOLD", 60)

        proposals = [{"ticker": "BTC", "proposed_action": "LONG",
                      "confidence": 80, "suggested_sl": 48000.0,
                      "suggested_tp": 56000.0, "position_size_pct": 10,
                      "quant_reasoning": "Strong breakout."}]

        fake_response = _make_anthropic_response(json.dumps(proposals))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_response)

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            result = await propose_trades([_ticker_data("BTC")],
                                          {"BTC": (70, "Neutral outlook")})

        assert len(result) == 1
        assert result[0]["ticker"] == "BTC"

    @pytest.mark.asyncio
    async def test_hold_action_filtered_out(self, monkeypatch):
        """HOLD proposals are never returned."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        proposals = [{"ticker": "ETH", "proposed_action": "HOLD", "confidence": 90,
                      "suggested_sl": 0.0, "suggested_tp": 0.0,
                      "position_size_pct": 5, "quant_reasoning": "Choppy market."}]

        fake_response = _make_anthropic_response(json.dumps(proposals))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_response)

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            result = await propose_trades([_ticker_data("ETH")], {})

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_low_confidence_passed_through(self, monkeypatch):
        """Low-confidence proposals are now passed through (engine handles filtering)."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        proposals = [{"ticker": "SOL", "proposed_action": "LONG", "confidence": 50,
                      "suggested_sl": 90.0, "suggested_tp": 130.0,
                      "position_size_pct": 5, "quant_reasoning": "Weak setup."}]

        fake_response = _make_anthropic_response(json.dumps(proposals))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_response)

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            result = await propose_trades([_ticker_data("SOL")], {})

        # Now passed through — engine-level threshold is the single gate
        assert len(result) == 1
        assert result[0]["ticker"] == "SOL"

    @pytest.mark.asyncio
    async def test_api_exception_returns_empty(self, monkeypatch):
        """API crash → returns [] without raising."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            result = await propose_trades([_ticker_data()], {})

        assert result == []

    @pytest.mark.asyncio
    async def test_memory_injected_into_prompt(self, monkeypatch):
        """recent_memory string appears in the call to the API."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        proposals = [{"ticker": "BTC", "proposed_action": "LONG", "confidence": 80,
                      "suggested_sl": 48000.0, "suggested_tp": 56000.0,
                      "position_size_pct": 10, "quant_reasoning": "Strong"}]

        fake_response = _make_anthropic_response(json.dumps(proposals))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_response)

        memory = "--- RECENT PERFORMANCE MEMORY --- WIN +5.2%"

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            await propose_trades([_ticker_data()], {}, recent_memory=memory)

        call_kwargs = mock_client.messages.create.call_args
        prompt_text = call_kwargs[1]["messages"][0]["content"]
        assert "RECENT PERFORMANCE MEMORY" in prompt_text

    @pytest.mark.asyncio
    async def test_empty_ticker_list_returns_empty(self, monkeypatch):
        """No ticker data provided → API not called, returns []."""
        import backend.src.core.agents.quant_analyst as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_anthropic_response("[]"))

        with patch("backend.src.core.agents.quant_analyst.AsyncAnthropic",
                   return_value=mock_client):
            result = await propose_trades([], {})

        assert result == []
