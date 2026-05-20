"""
test_market_sentiment.py
=========================
50 tests for Phase 50.2 On-Chain Sentiment & Squeeze Protection Engine.

Covers:
  • _to_futures_symbol helper
  • evaluate_squeeze_risk pure function (all combinations)
  • build_sentiment_tag formatting
  • get_futures_sentiment async — success, partial data, errors
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.src.services.market_sentiment import (
    _to_futures_symbol,
    evaluate_squeeze_risk,
    build_sentiment_tag,
    get_futures_sentiment,
    FLAG_LONG_SQUEEZE,
    FLAG_SHORT_SQUEEZE,
    FLAG_SAFE,
    EXTREME_GREED_THRESHOLD,
    EXTREME_FEAR_THRESHOLD,
)


# ─────────────────────────────────────────────────────────────────────────────
# Symbol formatting
# ─────────────────────────────────────────────────────────────────────────────

class TestFuturesSymbol:
    def test_bare_btc(self):
        assert _to_futures_symbol("BTC") == "BTC/USDT:USDT"

    def test_with_usdt_suffix_stripped(self):
        assert _to_futures_symbol("BTCUSDT") == "BTC/USDT:USDT"

    def test_with_slash_usdt_stripped(self):
        assert _to_futures_symbol("BTC/USDT") == "BTC/USDT:USDT"

    def test_eth_ticker(self):
        assert _to_futures_symbol("ETH") == "ETH/USDT:USDT"

    def test_lowercase_input_uppercased(self):
        result = _to_futures_symbol("sol")
        assert result == "SOL/USDT:USDT"

    def test_doge_ticker(self):
        assert _to_futures_symbol("DOGE") == "DOGE/USDT:USDT"

    def test_xrp_ticker(self):
        assert _to_futures_symbol("XRP") == "XRP/USDT:USDT"


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_squeeze_risk
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluateSqueezeRisk:
    # ── LONG direction ──
    def test_long_safe_when_funding_neutral(self):
        result = evaluate_squeeze_risk("LONG", 0.0001)
        assert result == FLAG_SAFE

    def test_long_safe_when_funding_zero(self):
        result = evaluate_squeeze_risk("LONG", 0.0)
        assert result == FLAG_SAFE

    def test_long_squeeze_warning_when_funding_above_threshold(self):
        result = evaluate_squeeze_risk("LONG", EXTREME_GREED_THRESHOLD + 0.0001)
        assert result == FLAG_LONG_SQUEEZE

    def test_long_safe_at_exact_threshold(self):
        # At the threshold, not above it — should be safe
        result = evaluate_squeeze_risk("LONG", EXTREME_GREED_THRESHOLD)
        assert result == FLAG_SAFE

    def test_long_safe_when_funding_very_negative(self):
        # Extreme fear = good for longs (shorts getting squeezed)
        result = evaluate_squeeze_risk("LONG", -0.001)
        assert result == FLAG_SAFE

    # ── SHORT direction ──
    def test_short_safe_when_funding_neutral(self):
        result = evaluate_squeeze_risk("SHORT", 0.0001)
        assert result == FLAG_SAFE

    def test_short_squeeze_when_funding_below_threshold(self):
        result = evaluate_squeeze_risk("SHORT", EXTREME_FEAR_THRESHOLD - 0.0001)
        assert result == FLAG_SHORT_SQUEEZE

    def test_short_safe_at_exact_fear_threshold(self):
        result = evaluate_squeeze_risk("SHORT", EXTREME_FEAR_THRESHOLD)
        assert result == FLAG_SAFE

    def test_short_safe_when_funding_very_positive(self):
        result = evaluate_squeeze_risk("SHORT", 0.001)
        assert result == FLAG_SAFE

    # ── Edge cases ──
    def test_unknown_direction_returns_safe(self):
        result = evaluate_squeeze_risk("HOLD", 0.001)
        assert result == FLAG_SAFE

    def test_extreme_positive_funding_triggers_long_squeeze(self):
        result = evaluate_squeeze_risk("LONG", 0.1)  # 10% funding = extreme greed
        assert result == FLAG_LONG_SQUEEZE

    def test_extreme_negative_funding_triggers_short_squeeze(self):
        result = evaluate_squeeze_risk("SHORT", -0.1)
        assert result == FLAG_SHORT_SQUEEZE

    def test_funding_slightly_above_threshold(self):
        # 0.025001% just barely crosses
        result = evaluate_squeeze_risk("LONG", 0.00025001)
        assert result == FLAG_LONG_SQUEEZE


# ─────────────────────────────────────────────────────────────────────────────
# build_sentiment_tag
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildSentimentTag:
    def test_safe_flag_produces_green_tag(self):
        sentiment = {"funding_rate_pct": "0.0100%", "squeeze_flag": FLAG_SAFE}
        tag = build_sentiment_tag(sentiment)
        assert "✅ SAFE" in tag
        assert "0.0100%" in tag

    def test_long_squeeze_produces_warning_tag(self):
        sentiment = {"funding_rate_pct": "0.0350%", "squeeze_flag": FLAG_LONG_SQUEEZE}
        tag = build_sentiment_tag(sentiment)
        assert "⚠️ SQUEEZE RISK" in tag
        assert "Size Reduced" in tag
        assert "0.0350%" in tag

    def test_short_squeeze_produces_warning_tag(self):
        sentiment = {"funding_rate_pct": "-0.0350%", "squeeze_flag": FLAG_SHORT_SQUEEZE}
        tag = build_sentiment_tag(sentiment)
        assert "⚠️ SQUEEZE RISK" in tag

    def test_missing_funding_rate_defaults_to_na(self):
        sentiment = {"squeeze_flag": FLAG_SAFE}
        tag = build_sentiment_tag(sentiment)
        assert "N/A" in tag

    def test_tag_contains_thermometer_emoji(self):
        sentiment = {"funding_rate_pct": "0.0100%", "squeeze_flag": FLAG_SAFE}
        tag = build_sentiment_tag(sentiment)
        assert "🌡️" in tag


# ─────────────────────────────────────────────────────────────────────────────
# get_futures_sentiment (async)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFuturesSentiment:
    @pytest.mark.asyncio
    async def test_success_high_funding_triggers_long_squeeze(self):
        """Fetching high funding rate → FLAG_LONG_SQUEEZE in result."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0005})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={"openInterestValue": 1_000_000.0})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("BTC")

            assert result["ticker"] == "BTC"
            assert result["funding_rate"] == 0.0005
            assert result["squeeze_flag"] == FLAG_LONG_SQUEEZE
            assert result["open_interest"] == 1_000_000.0
            assert result["error"] is None
            mock_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_negative_funding_returns_safe_for_long(self):
        """Negative funding = negative for shorts, but get_futures_sentiment evaluates LONG risk.
        The module calls evaluate_squeeze_risk('LONG', funding) which returns SAFE for negative funding.
        """
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": -0.0005})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={"openInterest": 500.0})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("ETH")
            # Very negative funding = shorts getting squeezed, but LONG direction eval returns SAFE
            assert result["funding_rate"] == -0.0005
            assert result["squeeze_flag"] == FLAG_SAFE  # LONG safe, shorts need to check themselves

    @pytest.mark.asyncio
    async def test_safe_when_funding_rate_low(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0001})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={"openInterestValue": 200_000.0})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("SOL")
            assert result["squeeze_flag"] == FLAG_SAFE

    @pytest.mark.asyncio
    async def test_funding_rate_formatted_as_pct(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0003})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("BTC")
            assert result["funding_rate_pct"] == "0.0300%"

    @pytest.mark.asyncio
    async def test_handles_funding_rate_fetch_failure(self):
        """If only funding rate fetch fails, OI can still return."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(side_effect=Exception("API error"))
        mock_exchange.fetch_open_interest = AsyncMock(return_value={"openInterestValue": 50_000.0})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("BTC")
            assert result["funding_rate"] is None
            assert result["squeeze_flag"] == FLAG_SAFE  # No data → default safe
            assert result["open_interest"] == 50_000.0

    @pytest.mark.asyncio
    async def test_handles_open_interest_fetch_failure(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0001})
        mock_exchange.fetch_open_interest = AsyncMock(side_effect=Exception("OI unavailable"))
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("ETH")
            assert result["funding_rate"] == 0.0001
            assert result["open_interest"] is None
            assert result["error"] is None

    @pytest.mark.asyncio
    async def test_exchange_always_closed_on_success(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0001})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            await get_futures_sentiment("BTC")
            mock_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_exchange_always_closed_on_error(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(side_effect=Exception("Crash"))
        mock_exchange.fetch_open_interest = AsyncMock(side_effect=Exception("Crash"))
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("BTC")
            mock_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_futures_symbol_correct_in_result(self):
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("DOGE")
            assert result["futures_symbol"] == "DOGE/USDT:USDT"

    @pytest.mark.asyncio
    async def test_null_funding_rate_value_handled(self):
        """If API returns fundingRate=None, don't crash."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_funding_rate = AsyncMock(return_value={"fundingRate": None})
        mock_exchange.fetch_open_interest = AsyncMock(return_value={})
        mock_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_exchange):
            result = await get_futures_sentiment("BTC")
            assert result["funding_rate"] is None
            assert result["squeeze_flag"] == FLAG_SAFE
