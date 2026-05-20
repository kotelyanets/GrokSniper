"""
test_regime_detector.py
========================
Tests for Phase 48 Market Regime Detection Engine.
Validates pure-function scoring, async live/fallback data fetching, and trading conditions.
"""

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from backend.src.services.regime_detector import (
    _score_regime,
    get_regime,
    should_trade,
    REGIME_PARAMS
)

class TestRegimeScoringPure:
    """Validates the pure mathematical scoring function for market regimes."""

    def test_strong_bull_regime(self):
        """BTC in uptrend, strong momentum, low chop → BULL."""
        result = _score_regime(
            close=65000.0,
            ema20=64000.0,
            ema50=62000.0,
            ema200=60000.0,
            rsi=65.0,
            adx=35.0,
            atr_pct=0.012,  # Trending calmly
            macd_hist=120.0
        )
        assert result.regime == "BULL"
        assert result.confidence >= 0.60
        assert result.bull_score > result.bear_score
        assert result.bull_score > result.chop_score
        assert "uptrend" in result.details.lower()
        assert result.params == REGIME_PARAMS["BULL"]

    def test_strong_bear_regime(self):
        """BTC in downtrend, bearish momentum, high ADX → BEAR."""
        result = _score_regime(
            close=55000.0,
            ema20=56000.0,
            ema50=58000.0,
            ema200=60000.0,
            rsi=35.0,
            adx=40.0,
            atr_pct=0.014,
            macd_hist=-250.0
        )
        assert result.regime == "BEAR"
        assert result.confidence >= 0.60
        assert result.bear_score > result.bull_score
        assert result.bear_score > result.chop_score
        assert "downtrend" in result.details.lower()
        assert result.params == REGIME_PARAMS["BEAR"]

    def test_choppy_neutral_regime(self):
        """Sideways market, low ADX, high volatility/chop → CHOP."""
        result = _score_regime(
            close=60000.0,
            ema20=60100.0,
            ema50=59900.0,
            ema200=60000.0,
            rsi=50.0,
            adx=15.0,  # Weak trend
            atr_pct=0.06,  # High volatility/chop
            macd_hist=5.0
        )
        assert result.regime == "CHOP"
        assert result.confidence >= 0.50
        assert result.chop_score > result.bull_score
        assert result.chop_score > result.bear_score
        assert "weak" in result.details.lower()
        assert result.params == REGIME_PARAMS["CHOP"]

    def test_moderate_neutral_trend(self):
        """Mixed signals result in a balanced regime classification."""
        result = _score_regime(
            close=61000.0,
            ema20=60500.0,
            ema50=61500.0,
            ema200=60000.0,  # Mixed EMA alignment
            rsi=52.0,
            adx=22.0,
            atr_pct=0.02,
            macd_hist=0.0
        )
        # Verify result is parsed without exception
        assert result.regime in ("BULL", "BEAR", "CHOP")
        assert 0.0 <= result.confidence <= 1.0


class TestShouldTradeLogic:
    """Validates that we sit out high-confidence choppy markets and trade others."""

    def test_chop_with_high_confidence_blocks_trading(self):
        """If we are in a definitive CHOP regime, should_trade is False."""
        mock_result = MagicMock()
        mock_result.regime = "CHOP"
        mock_result.confidence = 0.65
        assert should_trade(mock_result) is False

    def test_chop_with_low_confidence_allows_trading(self):
        """If CHOP confidence is very low (borderline), we can trade with strict params."""
        mock_result = MagicMock()
        mock_result.regime = "CHOP"
        mock_result.confidence = 0.45
        assert should_trade(mock_result) is True

    def test_bull_regime_always_allowed(self):
        mock_result = MagicMock()
        mock_result.regime = "BULL"
        mock_result.confidence = 0.90
        assert should_trade(mock_result) is True

    def test_bear_regime_always_allowed(self):
        mock_result = MagicMock()
        mock_result.regime = "BEAR"
        mock_result.confidence = 0.85
        assert should_trade(mock_result) is True


class TestRegimeDetectorAsync:
    """Validates live data fetches from the exchange and CCXT fallbacks."""

    @pytest.mark.asyncio
    async def test_get_regime_via_exchange_success(self):
        """If exchange service succeeds, get_regime uses it and returns structured regime."""
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(side_effect=[
            # 4h
            {
                "close": 65000.0, "ema_20": 64000.0, "ema_50": 63000.0,
                "ema_200": 60000.0, "rsi": 60.0, "atr": 1000.0, "adx": 32.0,
                "macd_line": 200.0, "macd_signal": 150.0
            },
            # 1d
            {"ema_200": 58000.0}
        ])

        result = await get_regime(exchange=mock_exchange)

        assert result.regime == "BULL"
        assert result.confidence > 0.5
        assert result.params == REGIME_PARAMS["BULL"]
        assert mock_exchange.get_technical_indicators.call_count == 2

    @pytest.mark.asyncio
    async def test_get_regime_exchange_fails_fallback_to_ccxt(self):
        """If exchange service throws an exception, get_regime falls back to direct ccxt fetching."""
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(side_effect=Exception("Exchange offline"))

        mock_ccxt_exchange = AsyncMock()
        mock_ccxt_exchange.fetch_ohlcv = AsyncMock(return_value=[
            # 50 mock historical candles [timestamp, open, high, low, close, volume]
            [1700000000 + i * 14400, 60000, 61000, 59000, 60500 + i * 10, 100]
            for i in range(100)
        ])
        mock_ccxt_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_exchange):
            result = await get_regime(exchange=mock_exchange)

            assert result.regime in ("BULL", "BEAR", "CHOP")
            mock_ccxt_exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT", "4h", limit=250)
            mock_ccxt_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_regime_insufficient_ccxt_candles(self):
        """If ccxt returns insufficient candles, defaults to CHOP regime with 50% confidence."""
        mock_ccxt_exchange = AsyncMock()
        mock_ccxt_exchange.fetch_ohlcv = AsyncMock(return_value=[[1700000000, 60000, 61000, 59000, 60500, 100]]) # only 1 candle
        mock_ccxt_exchange.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_exchange):
            result = await get_regime(exchange=None)

            assert result.regime == "CHOP"
            assert result.confidence == 0.50
            assert "insufficient" in result.details.lower()
            mock_ccxt_exchange.close.assert_called_once()
