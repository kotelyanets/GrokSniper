"""
test_risk_guardian.py
---------------------
Unit tests for backend/src/core/agents/risk_guardian.py.

The Anthropic client is fully mocked — no real API calls.
Run with:  pytest backend/tests/test_risk_guardian.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.core.agents.risk_guardian import (
    _extract_json_risk,
    evaluate_proposals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anthropic_response(content: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def _proposal(ticker="BTC", action="LONG", conf=80, size_pct=10):
    return {
        "ticker": ticker,
        "proposed_action": action,
        "confidence": conf,
        "suggested_sl": 48000.0,
        "suggested_tp": 56000.0,
        "position_size_pct": size_pct,
        "quant_reasoning": f"Strong {action} setup on {ticker}.",
    }


def _guardian_verdict(ticker="BTC", verdict="APPROVED", size_pct=10, reason="Looks safe."):
    return {
        "ticker": ticker,
        "verdict": verdict,
        "final_position_size_pct": size_pct,
        "risk_reasoning": reason,
    }


# ---------------------------------------------------------------------------
# _extract_json_risk — pure function
# ---------------------------------------------------------------------------

class TestExtractJsonRisk:

    def test_raw_array(self):
        raw = '[{"ticker": "BTC", "verdict": "APPROVED"}]'
        result = _extract_json_risk(raw)
        assert result[0]["verdict"] == "APPROVED"

    def test_fenced_json(self):
        data = [{"ticker": "ETH", "verdict": "REJECTED", "risk_reasoning": "BTC choppy."}]
        raw = f"```json\n{json.dumps(data)}\n```"
        result = _extract_json_risk(raw)
        assert result[0]["verdict"] == "REJECTED"

    def test_fence_no_lang(self):
        data = [{"ticker": "SOL", "verdict": "APPROVED"}]
        raw = f"```\n{json.dumps(data)}\n```"
        result = _extract_json_risk(raw)
        assert result[0]["ticker"] == "SOL"

    def test_array_with_preamble(self):
        data = [{"ticker": "ADA", "verdict": "REJECTED"}]
        raw = f"Risk assessment complete.\n{json.dumps(data)}"
        result = _extract_json_risk(raw)
        assert result[0]["ticker"] == "ADA"

    def test_single_object_wrapped_in_list(self):
        raw = '{"ticker": "BNB", "verdict": "APPROVED", "final_position_size_pct": 8}'
        result = _extract_json_risk(raw)
        assert isinstance(result, list)

    def test_invalid_text_raises_value_error(self):
        with pytest.raises(ValueError):
            _extract_json_risk("I refuse to provide a recommendation.")

    def test_empty_string_raises(self):
        with pytest.raises((ValueError, Exception)):
            _extract_json_risk("")


# ---------------------------------------------------------------------------
# evaluate_proposals — async, mock Anthropic
# ---------------------------------------------------------------------------

class TestEvaluateProposals:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self, monkeypatch):
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "")
        result = await evaluate_proposals([_proposal()], "BTC: Healthy", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_proposals_returns_empty(self, monkeypatch):
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")
        result = await evaluate_proposals([], "BTC: Healthy", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_approved_verdict_propagated(self, monkeypatch):
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        verdict = [_guardian_verdict("BTC", "APPROVED", 10, "All clear.")]
        fake_resp = _make_anthropic_response(json.dumps(verdict))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(
                [_proposal("BTC")], "BTC: healthy uptrend",
                [{"ticker": "BTC", "condensed": "BTC strong"}]
            )

        assert result[0]["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_rejected_verdict_propagated(self, monkeypatch):
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        verdict = [_guardian_verdict("ETH", "REJECTED", 10, "BTC is distribution.")]
        fake_resp = _make_anthropic_response(json.dumps(verdict))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(
                [_proposal("ETH")], "BTC: distribution",
                [{"ticker": "ETH", "condensed": "ETH choppy"}]
            )

        assert result[0]["verdict"] == "REJECTED"
        assert "distribution" in result[0]["risk_reasoning"].lower()

    @pytest.mark.asyncio
    async def test_guardian_reduces_position_size(self, monkeypatch):
        """Guardian can lower the Quant's proposed size."""
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        # Quant proposed 50%, guardian says only 10%
        verdict = [_guardian_verdict("BTC", "APPROVED", size_pct=10, reason="Reduced risk.")]
        fake_resp = _make_anthropic_response(json.dumps(verdict))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)

        proposal = _proposal("BTC", size_pct=50)

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(
                [proposal], "BTC: rallying",
                [{"ticker": "BTC", "condensed": "BTC rally"}]
            )

        # Final size must be min(quant, guardian) = 10
        assert result[0]["position_size_pct"] <= 10

    @pytest.mark.asyncio
    async def test_no_matching_ticker_defaults_to_rejected(self, monkeypatch):
        """Guardian returns verdicts for a different ticker → proposal defaults to REJECTED."""
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        # Guardian returns verdict for ETH but proposal is for BTC
        verdict = [_guardian_verdict("ETH", "APPROVED", 10, "ETH looks fine.")]
        fake_resp = _make_anthropic_response(json.dumps(verdict))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(
                [_proposal("BTC")], "BTC: context",
                [{"ticker": "BTC", "condensed": "BTC data"}]
            )

        assert result[0]["verdict"] == "REJECTED"

    @pytest.mark.asyncio
    async def test_api_exception_approves_all_fail_open(self, monkeypatch):
        """If the API crashes, all proposals are APPROVED (fail-open mode)."""
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("Guardian offline"))

        proposals = [_proposal("BTC"), _proposal("ETH")]

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(proposals, "BTC: ctx", [])

        assert all(p["verdict"] == "APPROVED" for p in result)
        assert all("GUARDIAN OFFLINE" in p["risk_reasoning"] for p in result)

    @pytest.mark.asyncio
    async def test_multiple_proposals_all_evaluated(self, monkeypatch):
        """Multiple proposals → all get a verdict."""
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        verdicts = [
            _guardian_verdict("BTC", "APPROVED", 10, "Strong."),
            _guardian_verdict("ETH", "REJECTED", 5, "Risky."),
            _guardian_verdict("SOL", "APPROVED", 8, "Good setup."),
        ]
        fake_resp = _make_anthropic_response(json.dumps(verdicts))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)

        proposals = [_proposal("BTC"), _proposal("ETH"), _proposal("SOL")]
        ticker_data = [{"ticker": t, "condensed": f"{t} data"} for t in ["BTC", "ETH", "SOL"]]

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            result = await evaluate_proposals(proposals, "BTC context", ticker_data)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_memory_injected_when_provided(self, monkeypatch):
        import backend.src.core.agents.risk_guardian as mod
        monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "test-key")

        verdict = [_guardian_verdict("BTC", "APPROVED")]
        fake_resp = _make_anthropic_response(json.dumps(verdict))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=fake_resp)
        memory = "--- RECENT PERFORMANCE MEMORY --- LOSS -3.2%"

        with patch("backend.src.core.agents.risk_guardian.AsyncAnthropic",
                   return_value=mock_client):
            await evaluate_proposals(
                [_proposal("BTC")], "BTC ctx",
                [{"ticker": "BTC", "condensed": "BTC"}],
                recent_memory=memory
            )

        call_kwargs = mock_client.messages.create.call_args
        prompt_text = call_kwargs[1]["messages"][0]["content"]
        assert "RECENT PERFORMANCE MEMORY" in prompt_text
