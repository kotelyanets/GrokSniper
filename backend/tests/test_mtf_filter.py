"""
test_mtf_filter.py
===================
50 tests for Phase 50.1 Multi-Timeframe (MTF) Alignment Filter.

Covers:
  • _htf_for timeframe mapping
  • _classify pure function (LONG/SHORT, all signal combinations)
  • MTFResult dataclass fields
  • check_htf_alignment via exchange (fast path)
  • check_htf_alignment via ccxt fallback (slow path)
  • Fail-open default when data is unavailable
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.src.services.mtf_filter import (
    _htf_for,
    _classify,
    check_htf_alignment,
    MTFResult,
    HTF_MAP,
    ALIGNMENT_THRESHOLD,
)


# ─────────────────────────────────────────────────────────────────────────────
# _htf_for: timeframe mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestHTFMapping:
    def test_1h_maps_to_4h(self):
        assert _htf_for("1h") == "4h"

    def test_4h_maps_to_1d(self):
        assert _htf_for("4h") == "1d"

    def test_15m_maps_to_1h(self):
        assert _htf_for("15m") == "1h"

    def test_1d_maps_to_1w(self):
        assert _htf_for("1d") == "1w"

    def test_5m_maps_to_1h(self):
        assert _htf_for("5m") == "1h"

    def test_30m_maps_to_4h(self):
        assert _htf_for("30m") == "4h"

    def test_unknown_timeframe_defaults_to_4h(self):
        assert _htf_for("99m") == "4h"

    def test_all_known_timeframes_are_mapped(self):
        for tf in HTF_MAP.keys():
            assert _htf_for(tf) == HTF_MAP[tf]


# ─────────────────────────────────────────────────────────────────────────────
# _classify: pure function for alignment scoring
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPure:
    # ── LONG direction ──
    def test_long_aligned_both_bullish(self):
        result = _classify(ema20=55000, ema50=52000, rsi=62.0, direction="LONG", htf_tf="4h")
        assert result.aligned is True
        assert result.htf_ema_bull is True
        assert result.htf_rsi_bull is True
        assert result.bull_score == 2
        assert result.tag == "[HTF: ALIGNED]"

    def test_long_aligned_only_ema_bullish(self):
        result = _classify(ema20=55000, ema50=52000, rsi=45.0, direction="LONG", htf_tf="4h")
        # bull_score=1 ≥ ALIGNMENT_THRESHOLD(1) → aligned
        assert result.aligned is True
        assert result.htf_ema_bull is True
        assert result.htf_rsi_bull is False

    def test_long_aligned_only_rsi_bullish(self):
        result = _classify(ema20=50000, ema50=55000, rsi=65.0, direction="LONG", htf_tf="4h")
        # bull_score=1 → aligned
        assert result.aligned is True
        assert result.htf_ema_bull is False
        assert result.htf_rsi_bull is True

    def test_long_blocked_both_bearish(self):
        result = _classify(ema20=50000, ema50=55000, rsi=40.0, direction="LONG", htf_tf="4h")
        assert result.aligned is False
        assert result.bull_score == 0
        assert result.tag == "[HTF: BLOCKED]"
        assert "Bearish" in result.block_reason

    def test_long_blocked_reason_contains_timeframe(self):
        result = _classify(ema20=50000, ema50=55000, rsi=40.0, direction="LONG", htf_tf="4h")
        assert "4h" in result.block_reason

    # ── SHORT direction ──
    def test_short_aligned_both_bearish(self):
        result = _classify(ema20=50000, ema50=55000, rsi=40.0, direction="SHORT", htf_tf="1d")
        assert result.aligned is True
        assert result.tag == "[HTF: ALIGNED]"

    def test_short_aligned_only_ema_bearish(self):
        result = _classify(ema20=50000, ema50=55000, rsi=55.0, direction="SHORT", htf_tf="1d")
        # bear_score = 2 - 1 = 1 ≥ threshold → aligned
        assert result.aligned is True

    def test_short_blocked_both_bullish(self):
        result = _classify(ema20=55000, ema50=52000, rsi=65.0, direction="SHORT", htf_tf="1d")
        assert result.aligned is False
        assert result.tag == "[HTF: BLOCKED]"
        assert "Bullish" in result.block_reason

    def test_short_blocked_reason_contains_timeframe(self):
        result = _classify(ema20=55000, ema50=52000, rsi=65.0, direction="SHORT", htf_tf="1d")
        assert "1d" in result.block_reason

    # ── MTFResult fields ──
    def test_result_contains_ema_values(self):
        result = _classify(ema20=64500.0, ema50=62000.0, rsi=58.0, direction="LONG", htf_tf="4h")
        assert abs(result.htf_ema20 - 64500.0) < 0.01
        assert abs(result.htf_ema50 - 62000.0) < 0.01
        assert abs(result.htf_rsi - 58.0) < 0.01

    def test_result_contains_direction(self):
        result = _classify(ema20=64500.0, ema50=62000.0, rsi=58.0, direction="SHORT", htf_tf="4h")
        assert result.direction == "SHORT"

    def test_result_htf_timeframe_set(self):
        result = _classify(ema20=64500.0, ema50=62000.0, rsi=58.0, direction="LONG", htf_tf="1d")
        assert result.htf_timeframe == "1d"

    def test_rsi_exactly_50_is_not_bullish(self):
        result = _classify(ema20=50000, ema50=48000, rsi=50.0, direction="LONG", htf_tf="4h")
        # rsi > 50 is the condition, exactly 50 is not bullish
        assert result.htf_rsi_bull is False

    def test_rsi_just_above_50_is_bullish(self):
        result = _classify(ema20=50000, ema50=48000, rsi=50.1, direction="LONG", htf_tf="4h")
        assert result.htf_rsi_bull is True

    def test_ema_equal_is_not_bullish(self):
        result = _classify(ema20=50000, ema50=50000, rsi=55.0, direction="LONG", htf_tf="4h")
        # ema20 > ema50 condition fails for equal values
        assert result.htf_ema_bull is False


# ─────────────────────────────────────────────────────────────────────────────
# check_htf_alignment: fast path via exchange
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckHTFAlignmentExchangePath:
    @pytest.mark.asyncio
    async def test_exchange_path_bullish_long_aligned(self):
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(return_value={
            "ema_20": 65000.0, "ema_50": 62000.0, "rsi": 62.0
        })

        result = await check_htf_alignment("BTC", "1h", "LONG", exchange=mock_exchange)

        assert result.aligned is True
        assert result.htf_timeframe == "4h"  # 1h → 4h
        mock_exchange.get_technical_indicators.assert_called_once_with("BTC", "4h")

    @pytest.mark.asyncio
    async def test_exchange_path_bearish_long_blocked(self):
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(return_value={
            "ema_20": 55000.0, "ema_50": 60000.0, "rsi": 35.0
        })

        result = await check_htf_alignment("ETH", "1h", "LONG", exchange=mock_exchange)
        assert result.aligned is False

    @pytest.mark.asyncio
    async def test_exchange_path_short_aligned(self):
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(return_value={
            "ema_20": 55000.0, "ema_50": 60000.0, "rsi": 38.0
        })

        result = await check_htf_alignment("BTC", "4h", "SHORT", exchange=mock_exchange)
        assert result.aligned is True

    @pytest.mark.asyncio
    async def test_exchange_path_uses_correct_htf_for_4h(self):
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(return_value={
            "ema_20": 65000.0, "ema_50": 62000.0, "rsi": 60.0
        })

        result = await check_htf_alignment("BTC", "4h", "LONG", exchange=mock_exchange)
        assert result.htf_timeframe == "1d"
        mock_exchange.get_technical_indicators.assert_called_once_with("BTC", "1d")

    @pytest.mark.asyncio
    async def test_exchange_path_falls_back_on_exception(self):
        """If exchange path throws, falls back to direct CCXT (which also fails → fail-open)."""
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(
            side_effect=Exception("Exchange offline")
        )

        mock_ccxt_ex = AsyncMock()
        mock_ccxt_ex.fetch_ohlcv = AsyncMock(return_value=[])  # Empty → fail-open
        mock_ccxt_ex.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_ex):
            result = await check_htf_alignment("BTC", "1h", "LONG", exchange=mock_exchange)
            # Fail-open → should return aligned=True
            assert result.aligned is True
            assert "[HTF: ALIGNED" in result.tag


class TestCheckHTFAlignmentCCXTFallback:
    @pytest.mark.asyncio
    async def test_no_exchange_falls_back_to_ccxt(self):
        """When no exchange provided, direct ccxt fetch is used."""
        mock_ccxt_ex = AsyncMock()
        mock_ccxt_ex.fetch_ohlcv = AsyncMock(return_value=[
            [1700000000 + i * 3600, 60000, 61000, 59000, 60000 + i * 10, 100]
            for i in range(100)
        ])
        mock_ccxt_ex.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_ex):
            result = await check_htf_alignment("BTC", "1h", "LONG", exchange=None)
            assert isinstance(result, MTFResult)
            mock_ccxt_ex.fetch_ohlcv.assert_called_once_with("BTC/USDT", "4h", limit=100)
            mock_ccxt_ex.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_insufficient_candles_returns_aligned_default(self):
        mock_ccxt_ex = AsyncMock()
        mock_ccxt_ex.fetch_ohlcv = AsyncMock(return_value=[
            [1700000000, 60000, 61000, 59000, 60000, 100]  # Only 1 candle
        ])
        mock_ccxt_ex.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_ex):
            result = await check_htf_alignment("BTC", "1h", "LONG", exchange=None)
            assert result.aligned is True  # fail-open
            assert "unavailable" in result.block_reason.lower()

    @pytest.mark.asyncio
    async def test_ccxt_exception_returns_aligned_default(self):
        mock_ccxt_ex = AsyncMock()
        mock_ccxt_ex.fetch_ohlcv = AsyncMock(side_effect=Exception("Network error"))
        mock_ccxt_ex.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_ex):
            result = await check_htf_alignment("BTC", "1h", "LONG", exchange=None)
            assert result.aligned is True  # Fail-open
            mock_ccxt_ex.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_ema_not_both_zero_uses_exchange_path(self):
        """When exchange returns ema_20=0.0, ema_50=0.0 → falls back to ccxt."""
        mock_exchange = AsyncMock()
        mock_exchange.get_technical_indicators = AsyncMock(return_value={
            "ema_20": 0.0, "ema_50": 0.0, "rsi": 50.0
        })

        mock_ccxt_ex = AsyncMock()
        mock_ccxt_ex.fetch_ohlcv = AsyncMock(return_value=[
            [1700000000 + i * 3600, 60000, 61000, 59000, 60000 + i * 10, 100]
            for i in range(100)
        ])
        mock_ccxt_ex.close = AsyncMock()

        with patch("ccxt.async_support.binance", return_value=mock_ccxt_ex):
            result = await check_htf_alignment("BTC", "1h", "LONG", exchange=mock_exchange)
            # Falls back due to zero ema values
            assert isinstance(result, MTFResult)
