"""
test_ai_analyzer.py
-------------------
Unit tests for backend/src/services/ai_analyzer.py.

All HTTP calls are mocked via unittest.mock so no real Groq API is needed.
Run with:  pytest backend/tests/test_ai_analyzer.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.services.ai_analyzer import SentimentResult, analyze_news


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _groq_response(payload: dict) -> MagicMock:
    """Build a fake httpx response object that returns `payload` as JSON."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "choices": [{"message": {"content": json.dumps(payload)}}]
    })
    return mock_resp


def _groq_response_raw(content: str) -> MagicMock:
    """Build a fake httpx response where choices[0].message.content is raw text."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "choices": [{"message": {"content": content}}]
    })
    return mock_resp


# ---------------------------------------------------------------------------
# Fallback behaviour (no key)
# ---------------------------------------------------------------------------

class TestAnalyzeNewsFallback:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock(self, monkeypatch):
        """With no GROQ_API_KEY the function returns mock sentiment."""
        import backend.src.services.ai_analyzer as mod
        monkeypatch.setattr(mod, "GROQ_API_KEY", None)
        result = await analyze_news("Some news text")
        assert isinstance(result, SentimentResult)

    @pytest.mark.asyncio
    async def test_no_api_key_mock_ticker_is_btc(self, monkeypatch):
        import backend.src.services.ai_analyzer as mod
        monkeypatch.setattr(mod, "GROQ_API_KEY", None)
        result = await analyze_news("Any text")
        assert result.ticker == "BTC"

    @pytest.mark.asyncio
    async def test_network_error_falls_back_to_mock(self):
        """Network failure → fallback SentimentResult, not a crash."""
        async def raise_exc(*args, **kwargs):
            raise ConnectionError("No internet")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=ConnectionError("timeout"))
            mock_client_cls.return_value = mock_client

            result = await analyze_news("ETH upgrade news")

        assert isinstance(result, SentimentResult)

    @pytest.mark.asyncio
    async def test_http_error_falls_back(self):
        """Non-200 HTTP → fallback."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())
            )
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await analyze_news("Some text")

        assert isinstance(result, SentimentResult)


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------

class TestAnalyzeNewsHappyPath:

    @pytest.mark.asyncio
    async def test_valid_json_response_parses_ticker(self):
        payload = {"ticker": "eth", "sentiment_score": 0.7, "confidence": 85, "reason": "bullish"}
        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response(payload))
            cls.return_value = m
            result = await analyze_news("ETH news")

        # ticker must be uppercased
        assert result.ticker == "ETH"

    @pytest.mark.asyncio
    async def test_sentiment_score_is_float(self):
        payload = {"ticker": "BTC", "sentiment_score": -0.4, "confidence": 60, "reason": "bearish"}
        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response(payload))
            cls.return_value = m
            result = await analyze_news("BTC dumps")

        assert isinstance(result.sentiment_score, float)

    @pytest.mark.asyncio
    async def test_confidence_is_int(self):
        payload = {"ticker": "SOL", "sentiment_score": 0.5, "confidence": 75, "reason": "neutral"}
        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response(payload))
            cls.return_value = m
            result = await analyze_news("SOL news")

        assert isinstance(result.confidence, int)

    @pytest.mark.asyncio
    async def test_json_inside_markdown_fence_is_extracted(self):
        """Response wrapped in ```json ... ``` still parses correctly."""
        raw_payload = {"ticker": "BNB", "sentiment_score": 0.3, "confidence": 55, "reason": "meh"}
        fenced = f"```json\n{json.dumps(raw_payload)}\n```"

        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response_raw(fenced))
            cls.return_value = m
            result = await analyze_news("BNB latest news")

        assert result.ticker == "BNB"

    @pytest.mark.asyncio
    async def test_json_inside_plain_fence_is_extracted(self):
        """Response wrapped in ``` ... ``` (no 'json' label) still parses."""
        raw_payload = {"ticker": "ADA", "sentiment_score": 0.1, "confidence": 50, "reason": "flat"}
        fenced = f"```\n{json.dumps(raw_payload)}\n```"

        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response_raw(fenced))
            cls.return_value = m
            result = await analyze_news("ADA update")

        assert result.ticker == "ADA"

    @pytest.mark.asyncio
    async def test_reason_field_populated(self):
        payload = {"ticker": "XRP", "sentiment_score": 0.9, "confidence": 92, "reason": "SEC case dismissed!"}
        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response(payload))
            cls.return_value = m
            result = await analyze_news("XRP news")

        assert "SEC" in result.reason

    @pytest.mark.asyncio
    async def test_returns_sentiment_result_type(self):
        payload = {"ticker": "DOGE", "sentiment_score": 0.0, "confidence": 20, "reason": "boring"}
        with patch("httpx.AsyncClient") as cls:
            m = MagicMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.post = AsyncMock(return_value=_groq_response(payload))
            cls.return_value = m
            result = await analyze_news("DOGE meme")

        assert isinstance(result, SentimentResult)
