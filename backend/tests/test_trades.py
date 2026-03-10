"""
test_trades.py
--------------
Focused tests for trade PnL calculations, live-trade stats extraction,
and the /api/trades endpoint in backend/src/api/routes.py.

All DB and exchange calls are fully mocked.
Run with:  pytest backend/tests/test_trades.py -v
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.src.services.risk_manager import (
    _compute_stats_from_live_trades,
    _compute_stats_from_paper_trades,
    MIN_TRADES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _live_trade(is_closed=True, reason="take_profit", price=50000.0,
                highest_price=55000.0, amount=0.01,
                position_size_usdt=500.0, side="LONG"):
    t = MagicMock()
    t.id = uuid4()
    t.ticker = "BTC"
    t.action = "BUY"
    t.side = side
    t.price = Decimal(str(price))
    t.highest_price = Decimal(str(highest_price)) if highest_price else None
    t.amount = Decimal(str(amount))
    t.position_size_usdt = position_size_usdt
    t.is_closed = is_closed
    t.reason = reason
    t.created_at = datetime(2026, 3, 10, 12, 0, 0)
    t.status = "success"
    t.parent_id = None
    t.stop_loss_price = price * 0.97
    t.lowest_price = None
    return t


def _paper_trade(ticker="BTC", pnl=10.0):
    t = MagicMock()
    t.ticker = ticker
    t.pnl_usdt = pnl
    t.status = "CLOSED"
    t.created_at = datetime(2026, 3, 10, 12, 0, 0)
    return t


# ---------------------------------------------------------------------------
# _compute_stats_from_live_trades — pure function (extended)
# ---------------------------------------------------------------------------

class TestComputeStatsFromLiveTrades:

    def test_insufficient_trades_returns_none(self):
        trades = [_live_trade()] * (MIN_TRADES - 1)
        assert _compute_stats_from_live_trades(trades) is None

    def test_open_trades_not_counted(self):
        """Only is_closed=True trades are counted toward Kelly stats."""
        open_trades = [_live_trade(is_closed=False)] * 20
        assert _compute_stats_from_live_trades(open_trades) is None

    def test_wins_from_profit_reason(self):
        """Trades with 'profit' in reason are classified as wins."""
        wins = [_live_trade(reason="take_profit", position_size_usdt=100.0)] * 8
        losses_mock = [_live_trade(reason="stop_loss", price=50000.0, highest_price=48000.0)] * 7
        stats = _compute_stats_from_live_trades(wins + losses_mock)
        assert stats is not None
        assert stats["win_rate"] > 0

    def test_losses_from_highest_below_price(self):
        """highest_price <= price means the position went down (loss)."""
        trades = [_live_trade(price=50000.0, highest_price=49000.0, reason="")] * 15
        stats = _compute_stats_from_live_trades(trades)
        # All are losses, so no wins → returns None
        assert stats is None

    def test_mixed_wins_and_losses(self):
        wins  = [_live_trade(reason="take_profit")] * 8
        losses = [_live_trade(price=50000.0, highest_price=49000.0, reason="")] * 7
        stats = _compute_stats_from_live_trades(wins + losses)
        assert stats is not None
        assert "win_rate" in stats
        assert "avg_win" in stats
        assert "avg_loss" in stats

    def test_n_trades_in_stats(self):
        wins  = [_live_trade(reason="take_profit")] * 6
        losses = [_live_trade(price=50000.0, highest_price=49000.0, reason="")] * 6
        stats = _compute_stats_from_live_trades(wins + losses)
        assert stats is not None
        assert stats["n_trades"] == 12

    def test_win_rate_is_fraction(self):
        wins  = [_live_trade(reason="take_profit")] * 6
        losses = [_live_trade(price=50000.0, highest_price=49000.0, reason="")] * 4
        stats = _compute_stats_from_live_trades(wins + losses)
        assert stats is not None
        assert 0.0 < stats["win_rate"] <= 1.0

    def test_all_wins_returns_none_no_losses(self):
        """All winning → no losses list → can't compute Kelly → None."""
        wins = [_live_trade(reason="take_profit")] * 15
        stats = _compute_stats_from_live_trades(wins)
        assert stats is None


# ---------------------------------------------------------------------------
# Comprehensive paper trade stats — parametrized win-rate scenarios
# ---------------------------------------------------------------------------

class TestPaperTradeWinRateScenarios:

    @pytest.mark.parametrize("wins,losses,expected_wr", [
        (10, 10, 0.50),
        (15, 5,  0.75),
        (5,  15, 0.25),
        (10, 0,  None),   # No losses → stats should be None
        (0,  10, None),   # No wins → stats should be None
        (20, 20, 0.50),
    ])
    def test_win_rate_for_scenarios(self, wins, losses, expected_wr):
        trades = (
            [_paper_trade(pnl=10.0)] * wins +
            [_paper_trade(pnl=-5.0)] * losses
        )
        stats = _compute_stats_from_paper_trades(trades)
        if expected_wr is None:
            assert stats is None
        else:
            assert stats is not None
            assert abs(stats["win_rate"] - expected_wr) < 0.001

    @pytest.mark.parametrize("avg_win_val,n_wins", [
        (5.0, 10),
        (100.0, 10),
        (0.01, 10),
    ])
    def test_avg_win_computed_correctly(self, avg_win_val, n_wins):
        trades = (
            [_paper_trade(pnl=avg_win_val)] * n_wins +
            [_paper_trade(pnl=-3.0)] * n_wins
        )
        stats = _compute_stats_from_paper_trades(trades)
        assert stats is not None
        assert abs(stats["avg_win"] - avg_win_val) < 0.001

    @pytest.mark.parametrize("avg_loss_val,n_losses", [
        (3.0, 10),
        (20.0, 10),
        (0.5,  12),
    ])
    def test_avg_loss_computed_correctly(self, avg_loss_val, n_losses):
        trades = (
            [_paper_trade(pnl=5.0)] * 10 +
            [_paper_trade(pnl=-avg_loss_val)] * n_losses
        )
        stats = _compute_stats_from_paper_trades(trades)
        assert stats is not None
        assert abs(stats["avg_loss"] - avg_loss_val) < 0.001


# ---------------------------------------------------------------------------
# Trade PnL calculation helpers (manual calculation tests)
# ---------------------------------------------------------------------------

class TestTradePnLCalculations:
    """Tests the PnL formulas used in routes.py manual_close endpoint."""

    def _long_pnl_pct(self, entry, exit_price):
        return ((exit_price - entry) / entry) * 100

    def _short_pnl_pct(self, entry, exit_price):
        return ((entry - exit_price) / entry) * 100

    def _long_pnl_usd(self, entry, exit_price, amount):
        return (exit_price - entry) * amount

    def _short_pnl_usd(self, entry, exit_price, amount):
        return (entry - exit_price) * amount

    # LONG PnL
    def test_long_win_pnl_percent(self):
        pct = self._long_pnl_pct(50000.0, 55000.0)
        assert abs(pct - 10.0) < 0.001

    def test_long_loss_pnl_percent(self):
        pct = self._long_pnl_pct(50000.0, 48500.0)
        assert pct < 0
        assert abs(pct - (-3.0)) < 0.001

    def test_long_breakeven_pnl(self):
        pct = self._long_pnl_pct(50000.0, 50000.0)
        assert pct == 0.0

    def test_long_pnl_usd_positive(self):
        usd = self._long_pnl_usd(50000.0, 55000.0, 0.01)
        assert abs(usd - 50.0) < 0.001

    def test_long_pnl_usd_negative(self):
        usd = self._long_pnl_usd(50000.0, 48500.0, 0.01)
        assert usd < 0

    # SHORT PnL
    def test_short_win_pnl_percent(self):
        """SHORT profits when price falls."""
        pct = self._short_pnl_pct(50000.0, 45000.0)
        assert abs(pct - 10.0) < 0.001

    def test_short_loss_pnl_percent(self):
        """SHORT loses when price rises."""
        pct = self._short_pnl_pct(50000.0, 51500.0)
        assert pct < 0

    def test_short_breakeven(self):
        pct = self._short_pnl_pct(50000.0, 50000.0)
        assert pct == 0.0

    def test_short_pnl_usd_positive(self):
        usd = self._short_pnl_usd(50000.0, 45000.0, 0.01)
        assert abs(usd - 50.0) < 0.001

    def test_short_pnl_usd_negative(self):
        usd = self._short_pnl_usd(50000.0, 52000.0, 0.01)
        assert usd < 0

    # Stop-loss / take-profit boundaries
    def test_stop_loss_3pct_below_entry(self):
        entry = 50000.0
        stop = entry * 0.97
        pct = self._long_pnl_pct(entry, stop)
        assert abs(pct - (-3.0)) < 0.001

    def test_take_profit_10pct_above_entry(self):
        entry = 50000.0
        tp = entry * 1.10
        pct = self._long_pnl_pct(entry, tp)
        assert abs(pct - 10.0) < 0.001

    @pytest.mark.parametrize("entry,exit_p,expected_pct", [
        (10000.0, 11000.0,  10.0),
        (10000.0,  9700.0,  -3.0),
        (50000.0, 52500.0,   5.0),
        (50000.0, 48500.0,  -3.0),
        (100.0,   110.0,    10.0),
    ])
    def test_long_pnl_parametrize(self, entry, exit_p, expected_pct):
        pct = self._long_pnl_pct(entry, exit_p)
        assert abs(pct - expected_pct) < 0.01


# ---------------------------------------------------------------------------
# /api/trades endpoint — integration tests (mock DB)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trades_client():
    mock_exchange = AsyncMock()
    mock_exchange.get_balance = AsyncMock(return_value={"total_usdt": 1000.0, "holdings": []})
    with (
        patch("backend.src.api.routes._exchange", mock_exchange),
        patch("backend.src.db.database.AsyncSessionLocal"),
    ):
        from backend.src.api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _full_trade_mock(ticker="BTC", action="BUY", price=50000.0,
                     highest_price=55000.0, amount=0.01,
                     position_size_usdt=500.0, is_closed=False,
                     side="LONG", reason="autotrade"):
    t = MagicMock()
    t.id = uuid4()
    t.ticker = ticker
    t.action = action
    t.side = side
    t.price = Decimal(str(price))
    t.highest_price = Decimal(str(highest_price)) if highest_price else None
    t.lowest_price = None
    t.amount = Decimal(str(amount))
    t.position_size_usdt = position_size_usdt
    t.stop_loss_price = price * 0.97
    t.is_closed = is_closed
    t.reason = reason
    t.status = "success"
    t.parent_id = None
    t.created_at = datetime(2026, 3, 10, 12, 0, 0)
    return t


class TestTradesEndpointWithData:

    def _session_cm(self, rows):
        res = MagicMock()
        res.scalars.return_value.all.return_value = rows
        sess = AsyncMock()
        sess.execute = AsyncMock(return_value=res)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=sess)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def test_empty_trades_returns_list(self, trades_client):
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([])):
            resp = trades_client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_trade_in_response(self, trades_client):
        trade = _full_trade_mock("BTC", "BUY")
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "BTC"
        assert data[0]["action"] == "BUY"

    def test_multiple_trades_returned(self, trades_client):
        trades = [_full_trade_mock(t) for t in ["BTC", "ETH", "SOL"]]
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm(trades)):
            resp = trades_client.get("/api/trades")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_trade_price_is_float(self, trades_client):
        trade = _full_trade_mock("BTC", price=67500.0)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        data = resp.json()
        assert isinstance(data[0]["price"], (int, float))
        assert abs(data[0]["price"] - 67500.0) < 0.01

    def test_closed_trade_is_closed_field(self, trades_client):
        trade = _full_trade_mock("ETH", is_closed=True)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        data = resp.json()
        assert data[0]["is_closed"] is True

    def test_open_trade_not_closed(self, trades_client):
        trade = _full_trade_mock("SOL", is_closed=False)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        data = resp.json()
        assert data[0]["is_closed"] is False

    def test_trade_status_normalized_to_success(self, trades_client):
        """Routes normalizes 'filled', 'completed', 'success' → 'success'."""
        for raw_status in ("filled", "completed", "success"):
            trade = _full_trade_mock("BTC")
            trade.status = raw_status
            with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
                resp = trades_client.get("/api/trades")
            data = resp.json()
            assert data[0]["status"] == "success", f"Expected 'success' for raw status '{raw_status}'"

    def test_short_trade_side_field(self, trades_client):
        trade = _full_trade_mock("BTC", side="SHORT")
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        data = resp.json()
        assert data[0]["side"] == "SHORT"

    def test_all_required_fields_present(self, trades_client):
        trade = _full_trade_mock("BTC")
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=self._session_cm([trade])):
            resp = trades_client.get("/api/trades")
        item = resp.json()[0]
        for field in ("id", "ticker", "action", "amount", "price",
                      "is_closed", "status", "created_at"):
            assert field in item, f"Missing field: {field}"
