"""
test_analytics.py
-----------------
Focused tests for the /api/analytics endpoint and the underlying PnL,
win-rate, and equity-curve calculations in backend/src/api/routes.py.

All DB calls are mocked — no real PostgreSQL required.
Run with:  pytest backend/tests/test_analytics.py -v
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper_trade(ticker="BTC", pnl=10.0, days_ago=0):
    """Build a fake PaperTrade-like object."""
    t = MagicMock()
    t.ticker = ticker
    t.pnl_usdt = pnl
    t.status = "CLOSED"
    t.created_at = datetime(2026, 3, 10, 12, 0, 0) - timedelta(days=days_ago)
    return t


def _mock_session_with_trades(trades):
    """Patch AsyncSessionLocal to return a mock session yielding `trades`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = trades

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Pure analytics math — extracted from routes.py logic
# ---------------------------------------------------------------------------

class TestWinRateMath:
    """Tests that replicate the exact win_rate formula used in /api/analytics."""

    def _calc_win_rate(self, trades):
        winning = sum(1 for t in trades if t.pnl_usdt is not None and t.pnl_usdt > 0)
        if not trades:
            return 0.0
        return round(winning / len(trades) * 100, 2)

    def test_100pct_win_rate(self):
        trades = [_paper_trade(pnl=10.0)] * 5
        assert self._calc_win_rate(trades) == 100.0

    def test_0pct_win_rate(self):
        trades = [_paper_trade(pnl=-5.0)] * 5
        assert self._calc_win_rate(trades) == 0.0

    def test_50pct_win_rate(self):
        trades = [_paper_trade(pnl=10.0)] * 5 + [_paper_trade(pnl=-5.0)] * 5
        assert self._calc_win_rate(trades) == 50.0

    def test_exact_fraction_rounds_to_2dp(self):
        """7 wins out of 10 → 70.00%"""
        trades = [_paper_trade(pnl=10.0)] * 7 + [_paper_trade(pnl=-5.0)] * 3
        assert self._calc_win_rate(trades) == 70.0

    def test_non_round_percentage(self):
        """3 wins out of 7 = 42.857...% → 42.86%"""
        trades = [_paper_trade(pnl=10.0)] * 3 + [_paper_trade(pnl=-5.0)] * 4
        assert self._calc_win_rate(trades) == 42.86

    def test_none_pnl_skipped_in_win_count(self):
        """Trades with pnl=None don't count as wins."""
        trades = [_paper_trade(pnl=None)] * 3 + [_paper_trade(pnl=10.0)] * 2
        wr = self._calc_win_rate(trades)
        # 2 wins out of 5 total = 40.0%
        assert wr == 40.0

    def test_zero_pnl_is_not_a_win(self):
        """Breakeven (pnl=0) is NOT counted as a win."""
        trades = [_paper_trade(pnl=0.0)] * 5
        assert self._calc_win_rate(trades) == 0.0

    def test_single_win(self):
        trades = [_paper_trade(pnl=5.0)]
        assert self._calc_win_rate(trades) == 100.0

    def test_single_loss(self):
        trades = [_paper_trade(pnl=-5.0)]
        assert self._calc_win_rate(trades) == 0.0


class TestPnLMath:
    """Tests for total_pnl and equity-curve calculations."""

    def _calc_total_pnl(self, trades):
        return round(sum(t.pnl_usdt for t in trades if t.pnl_usdt is not None), 2)

    def _build_equity_curve(self, trades):
        curve, cumulative = [], 0.0
        for t in trades:
            pnl = t.pnl_usdt or 0.0
            cumulative += pnl
            curve.append({"cumulative_pnl": round(cumulative, 2), "trade_pnl": round(pnl, 2), "ticker": t.ticker})
        return curve

    def test_positive_total_pnl(self):
        trades = [_paper_trade(pnl=50.0), _paper_trade(pnl=30.0)]
        assert self._calc_total_pnl(trades) == 80.0

    def test_negative_total_pnl(self):
        trades = [_paper_trade(pnl=-20.0), _paper_trade(pnl=-15.0)]
        assert self._calc_total_pnl(trades) == -35.0

    def test_net_zero_pnl(self):
        trades = [_paper_trade(pnl=50.0), _paper_trade(pnl=-50.0)]
        assert self._calc_total_pnl(trades) == 0.0

    def test_none_pnl_excluded_from_total(self):
        trades = [_paper_trade(pnl=100.0), _paper_trade(pnl=None)]
        assert self._calc_total_pnl(trades) == 100.0

    def test_equity_curve_cumulative_is_running_sum(self):
        trades = [_paper_trade(pnl=10.0), _paper_trade(pnl=20.0), _paper_trade(pnl=-5.0)]
        curve = self._build_equity_curve(trades)
        assert curve[0]["cumulative_pnl"] == 10.0
        assert curve[1]["cumulative_pnl"] == 30.0
        assert curve[2]["cumulative_pnl"] == 25.0

    def test_equity_curve_length_matches_trade_count(self):
        trades = [_paper_trade(pnl=5.0)] * 7
        curve = self._build_equity_curve(trades)
        assert len(curve) == 7

    def test_equity_curve_individual_pnl_stored(self):
        trades = [_paper_trade(pnl=15.0), _paper_trade(pnl=-8.0)]
        curve = self._build_equity_curve(trades)
        assert curve[0]["trade_pnl"] == 15.0
        assert curve[1]["trade_pnl"] == -8.0

    def test_equity_curve_ticker_stored(self):
        trades = [_paper_trade(ticker="BTC", pnl=10.0), _paper_trade(ticker="ETH", pnl=5.0)]
        curve = self._build_equity_curve(trades)
        assert curve[0]["ticker"] == "BTC"
        assert curve[1]["ticker"] == "ETH"

    def test_equity_curve_empty_trades(self):
        curve = self._build_equity_curve([])
        assert curve == []

    def test_pnl_rounded_to_2dp(self):
        trades = [_paper_trade(pnl=0.1 + 0.2)]   # classic float precision
        assert self._calc_total_pnl(trades) == round(0.1 + 0.2, 2)


class TestAnalyticsCalculations:
    """Integration-style checks combining win_rate + pnl + equity_curve."""

    def _full_analytics(self, trades):
        if not trades:
            return {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "equity_curve": []}
        winning = sum(1 for t in trades if t.pnl_usdt is not None and t.pnl_usdt > 0)
        total_pnl = sum(t.pnl_usdt for t in trades if t.pnl_usdt is not None)
        equity_curve, cumulative = [], 0.0
        for t in trades:
            pnl = t.pnl_usdt or 0.0
            cumulative += pnl
            equity_curve.append({
                "date": t.created_at.isoformat(),
                "cumulative_pnl": round(cumulative, 2),
                "trade_pnl": round(pnl, 2),
                "ticker": t.ticker,
            })
        return {
            "total_trades": len(trades),
            "win_rate": round(winning / len(trades) * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "equity_curve": equity_curve,
        }

    def test_empty_trades_returns_zeros(self):
        result = self._full_analytics([])
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] == 0.0
        assert result["equity_curve"] == []

    def test_single_winning_trade(self):
        trades = [_paper_trade(ticker="BTC", pnl=100.0)]
        result = self._full_analytics(trades)
        assert result["total_trades"] == 1
        assert result["win_rate"] == 100.0
        assert result["total_pnl"] == 100.0
        assert len(result["equity_curve"]) == 1
        assert result["equity_curve"][0]["cumulative_pnl"] == 100.0

    def test_single_losing_trade(self):
        trades = [_paper_trade(ticker="ETH", pnl=-50.0)]
        result = self._full_analytics(trades)
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] == -50.0

    def test_mixed_streak_scenario(self):
        """Simulates a realistic trading streak: 3 wins, 2 losses."""
        trades = [
            _paper_trade("BTC", pnl=120.0, days_ago=5),
            _paper_trade("ETH", pnl=-40.0, days_ago=4),
            _paper_trade("SOL", pnl=80.0, days_ago=3),
            _paper_trade("BTC", pnl=55.0, days_ago=2),
            _paper_trade("ETH", pnl=-30.0, days_ago=1),
        ]
        result = self._full_analytics(trades)
        assert result["total_trades"] == 5
        assert result["win_rate"] == 60.0
        assert result["total_pnl"] == 185.0
        # Equity curve: 120, 80, 160, 215, 185
        curve_vals = [p["cumulative_pnl"] for p in result["equity_curve"]]
        assert curve_vals == [120.0, 80.0, 160.0, 215.0, 185.0]

    def test_all_same_ticker(self):
        """Multiple trades on same ticker sum correctly."""
        trades = [_paper_trade("BTC", pnl=50.0)] * 4
        result = self._full_analytics(trades)
        assert result["total_pnl"] == 200.0
        assert result["win_rate"] == 100.0

    @pytest.mark.parametrize("n_wins,n_losses,expected_wr", [
        (10, 0,  100.0),
        (0,  10, 0.0),
        (5,  5,  50.0),
        (8,  2,  80.0),
        (1,  9,  10.0),
        (3,  7,  30.0),
    ])
    def test_win_rate_parametrize(self, n_wins, n_losses, expected_wr):
        trades = [_paper_trade(pnl=10.0)] * n_wins + [_paper_trade(pnl=-5.0)] * n_losses
        result = self._full_analytics(trades)
        assert result["win_rate"] == expected_wr


# ---------------------------------------------------------------------------
# /api/analytics endpoint integration-style tests (mock DB)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def analytics_client():
    """TestClient with fully mocked DB for analytics endpoint."""
    mock_exchange = AsyncMock()
    mock_exchange.get_balance = AsyncMock(return_value={"total_usdt": 1000.0, "holdings": []})

    with (
        patch("backend.src.api.routes._exchange", mock_exchange),
        patch("backend.src.db.database.AsyncSessionLocal"),
    ):
        from backend.src.api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestAnalyticsEndpointWithData:

    def test_no_trades_returns_zero_structure(self, analytics_client):
        """Empty DB → returns zeroed structure (not a server error)."""
        trades_cm = _mock_session_with_trades([])
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("total_trades", 0) == 0
        assert data.get("win_rate", 0.0) == 0.0
        assert data.get("equity_curve", []) == []

    def test_with_winning_trades_win_rate_above_50(self, analytics_client):
        """3 wins + 1 loss → win_rate = 75.0%"""
        trades = [
            _paper_trade("BTC", pnl=50.0),
            _paper_trade("ETH", pnl=30.0),
            _paper_trade("SOL", pnl=25.0),
            _paper_trade("BTC", pnl=-20.0),
        ]
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("win_rate") == 75.0

    def test_with_all_losses_win_rate_is_zero(self, analytics_client):
        trades = [_paper_trade("BTC", pnl=-30.0)] * 3
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("win_rate") == 0.0

    def test_total_pnl_is_sum(self, analytics_client):
        trades = [
            _paper_trade("BTC", pnl=100.0),
            _paper_trade("ETH", pnl=50.0),
            _paper_trade("SOL", pnl=-30.0),
        ]
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("total_pnl") == 120.0

    def test_equity_curve_has_correct_length(self, analytics_client):
        trades = [_paper_trade(pnl=10.0)] * 6
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("equity_curve", [])) == 6

    def test_equity_curve_cumulative_pnl_is_monotonic_on_all_wins(self, analytics_client):
        """All winning trades → equity curve strictly increases."""
        trades = [_paper_trade(pnl=10.0 * (i + 1)) for i in range(4)]
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        assert resp.status_code == 200
        curve = resp.json().get("equity_curve", [])
        cumulative_vals = [pt["cumulative_pnl"] for pt in curve]
        assert cumulative_vals == sorted(cumulative_vals)

    def test_response_schema_has_all_fields(self, analytics_client):
        trades = [_paper_trade(pnl=10.0)]
        trades_cm = _mock_session_with_trades(trades)
        with patch("backend.src.api.routes.AsyncSessionLocal", return_value=trades_cm):
            resp = analytics_client.get("/api/analytics")
        data = resp.json()
        for field in ("total_trades", "win_rate", "total_pnl", "equity_curve"):
            assert field in data, f"Missing field: {field}"
