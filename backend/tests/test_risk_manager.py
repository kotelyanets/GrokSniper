"""
test_risk_manager.py
--------------------
Unit tests for backend/src/services/risk_manager.py.

Pure math functions are tested directly.
DB-dependent functions use AsyncMock.
Run with:  pytest backend/tests/test_risk_manager.py -v
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.services.risk_manager import (
    FALLBACK_FRACTION,
    MAX_KELLY,
    MIN_KELLY,
    MIN_TRADES,
    calculate_kelly_percentage,
    _compute_stats_from_paper_trades,
    _compute_stats_from_live_trades,
    get_dynamic_position_size,
)


# ---------------------------------------------------------------------------
# calculate_kelly_percentage — pure function
# ---------------------------------------------------------------------------

class TestCalculateKellyPercentage:

    def test_typical_inputs_in_range(self):
        frac = calculate_kelly_percentage(win_rate=0.55, avg_win=10.0, avg_loss=7.0)
        assert MIN_KELLY <= frac <= MAX_KELLY

    def test_zero_avg_loss_returns_fallback(self):
        frac = calculate_kelly_percentage(win_rate=0.6, avg_win=10.0, avg_loss=0.0)
        assert frac == FALLBACK_FRACTION

    def test_negative_avg_loss_returns_fallback(self):
        frac = calculate_kelly_percentage(win_rate=0.6, avg_win=10.0, avg_loss=-5.0)
        assert frac == FALLBACK_FRACTION

    def test_losing_strategy_returns_min_kelly(self):
        """Win rate 20%, catastrophic → Kelly is negative → clamped to MIN_KELLY."""
        frac = calculate_kelly_percentage(win_rate=0.20, avg_win=1.0, avg_loss=10.0)
        assert frac == MIN_KELLY

    def test_result_never_exceeds_max_kelly(self):
        """Even with 95% win rate result must not exceed 20%."""
        frac = calculate_kelly_percentage(win_rate=0.95, avg_win=100.0, avg_loss=1.0)
        assert frac <= MAX_KELLY

    def test_result_never_below_min_kelly(self):
        frac = calculate_kelly_percentage(win_rate=0.51, avg_win=2.0, avg_loss=2.0)
        assert frac >= MIN_KELLY

    def test_half_kelly_dampening(self):
        """Half-Kelly (fraction=0.5) must be at most half of full Kelly."""
        W = 0.60
        avg_win = 10.0
        avg_loss = 6.0
        RR = avg_win / avg_loss
        full_kelly = max(W - (1 - W) / RR, 0.0)
        half_kelly = calculate_kelly_percentage(W, avg_win, avg_loss, fraction=0.5)
        # Half Kelly (before cap) ≤ full Kelly (before cap)
        assert half_kelly <= max(full_kelly, MIN_KELLY) + 1e-9

    def test_returns_float(self):
        result = calculate_kelly_percentage(0.55, 10.0, 8.0)
        assert isinstance(result, float)

    def test_custom_fraction_parameter(self):
        """A fraction of 1.0 should give full Kelly (capped at MAX_KELLY)."""
        full = calculate_kelly_percentage(0.55, 10.0, 8.0, fraction=1.0)
        half = calculate_kelly_percentage(0.55, 10.0, 8.0, fraction=0.5)
        assert full >= half


# ---------------------------------------------------------------------------
# _compute_stats_from_paper_trades — pure function
# ---------------------------------------------------------------------------

class TestComputeStatsFromPaperTrades:

    def _mock_trade(self, pnl):
        t = MagicMock()
        t.pnl_usdt = pnl
        return t

    def test_fewer_than_min_trades_returns_none(self):
        trades = [self._mock_trade(10.0)] * (MIN_TRADES - 1)
        assert _compute_stats_from_paper_trades(trades) is None

    def test_no_losses_returns_none(self):
        """All winning trades — cannot compute Kelly without losses."""
        trades = [self._mock_trade(5.0)] * 15
        assert _compute_stats_from_paper_trades(trades) is None

    def test_no_wins_returns_none(self):
        """All losing trades."""
        trades = [self._mock_trade(-5.0)] * 15
        assert _compute_stats_from_paper_trades(trades) is None

    def test_mixed_trades_returns_dict(self):
        wins  = [self._mock_trade(10.0)] * 7
        losses = [self._mock_trade(-5.0)] * 8
        stats = _compute_stats_from_paper_trades(wins + losses)
        assert stats is not None
        assert "win_rate" in stats
        assert "avg_win" in stats
        assert "avg_loss" in stats
        assert "n_trades" in stats

    def test_correct_win_rate(self):
        wins  = [self._mock_trade(10.0)] * 8
        losses = [self._mock_trade(-5.0)] * 7
        stats = _compute_stats_from_paper_trades(wins + losses)
        assert abs(stats["win_rate"] - 8 / 15) < 0.01

    def test_correct_avg_win(self):
        wins  = [self._mock_trade(12.0)] * 5 + [self._mock_trade(8.0)] * 5
        losses = [self._mock_trade(-6.0)] * 10
        stats = _compute_stats_from_paper_trades(wins + losses)
        assert abs(stats["avg_win"] - 10.0) < 0.01

    def test_correct_avg_loss(self):
        wins  = [self._mock_trade(10.0)] * 10
        losses = [self._mock_trade(-4.0)] * 6 + [self._mock_trade(-8.0)] * 4
        stats = _compute_stats_from_paper_trades(wins + losses)
        expected_loss = (6 * 4.0 + 4 * 8.0) / 10
        assert abs(stats["avg_loss"] - expected_loss) < 0.01

    def test_trades_with_none_pnl_are_excluded(self):
        """Trades where pnl_usdt is None should be skipped."""
        valid = [self._mock_trade(10.0)] * 6 + [self._mock_trade(-5.0)] * 5
        nulls = [self._mock_trade(None)] * 5
        stats = _compute_stats_from_paper_trades(valid + nulls)
        assert stats is not None


# ---------------------------------------------------------------------------
# get_dynamic_position_size — async, mock DB
# ---------------------------------------------------------------------------

class TestGetDynamicPositionSize:

    def _paper_trade(self, pnl):
        t = MagicMock()
        t.pnl_usdt = pnl
        t.status = "CLOSED"
        return t

    @pytest.mark.asyncio
    async def test_no_history_returns_fallback(self):
        """Empty DB → fallback fraction (5%)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        usdt, desc = await get_dynamic_position_size(session, 1000.0, paper_trade=True)

        expected = 1000.0 * FALLBACK_FRACTION
        assert abs(usdt - expected) < 0.01
        assert "FALLBACK" in desc

    @pytest.mark.asyncio
    async def test_sufficient_history_returns_kelly_size(self):
        """With enough history, returns Kelly-computed size."""
        wins  = [self._paper_trade(12.0)] * 20
        losses = [self._paper_trade(-6.0)] * 15

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = wins + losses

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        usdt, desc = await get_dynamic_position_size(session, 2000.0, paper_trade=True)

        assert usdt >= 10.0  # At least Binance minimum
        assert isinstance(usdt, float)
        assert "Kelly" in desc or "FALLBACK" in desc  # Either computed or fallback

    @pytest.mark.asyncio
    async def test_db_exception_returns_fallback(self):
        """DB crash → safe fallback, no exception raised."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB is down"))

        usdt, desc = await get_dynamic_position_size(session, 500.0, paper_trade=True)

        assert usdt == pytest.approx(500.0 * FALLBACK_FRACTION, abs=1.0)

    @pytest.mark.asyncio
    async def test_fallback_scales_with_balance(self):
        """Fallback is 5% of balance (no $10 floor in the fallback path)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        # 5% of $1000 = $50
        usdt, desc = await get_dynamic_position_size(session, 1000.0, paper_trade=True)
        assert abs(usdt - 1000.0 * FALLBACK_FRACTION) < 0.01

    @pytest.mark.asyncio
    async def test_kelly_path_applies_10_usdt_floor(self):
        """When Kelly-computed size is tiny, $10 floor is applied."""
        # 15 losing trades and 5 tiny wins → Kelly signals very small size
        wins   = [self._paper_trade(0.01)] * 5
        losses = [self._paper_trade(-50.0)] * 10

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = wins + losses

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        usdt, _ = await get_dynamic_position_size(session, 1000.0, paper_trade=True)
        # Either fallback OR at-least-$10 Kelly floor applies
        assert usdt >= 10.0 or usdt == pytest.approx(1000.0 * FALLBACK_FRACTION, abs=1.0)

    @pytest.mark.asyncio
    async def test_returns_tuple(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await get_dynamic_position_size(session, 1000.0)
        assert isinstance(result, tuple)
        assert len(result) == 2
