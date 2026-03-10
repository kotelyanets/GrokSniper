"""
test_memory_manager.py
----------------------
Unit tests for backend/src/services/memory_manager.py.

The database session is fully mocked so no real DB is needed.
Run with:  pytest backend/tests/test_memory_manager.py -v
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.services.memory_manager import fetch_recent_performance_memory


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _mock_trade(ticker="BTC", action="LONG", side="LONG",
                entry_price=50000.0, exit_price=55000.0,
                reason="breakout confirmed", ai_reasoning=None,
                created_at=None):
    """Build a fake trade-like object."""
    t = MagicMock()
    t.ticker = ticker
    t.action = action
    t.side = side
    t.entry_price = Decimal(str(entry_price))
    t.exit_price = Decimal(str(exit_price))
    t.reason = reason
    t.ai_reasoning = ai_reasoning
    t.created_at = created_at or datetime(2026, 3, 10, 12, 0, 0)
    return t


def _make_async_ctx(live_trades, paper_trades, raise_exc=False):
    """Build an async context manager mock for get_session()."""

    def make_result(rows):
        res = MagicMock()
        res.scalars.return_value.all.return_value = rows
        return res

    session = AsyncMock()
    if raise_exc:
        session.execute = AsyncMock(side_effect=RuntimeError("DB error"))
    else:
        session.execute = AsyncMock(side_effect=[
            make_result(live_trades),
            make_result(paper_trades),
        ])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFetchRecentPerformanceMemory:

    @pytest.mark.asyncio
    async def test_empty_db_returns_start_fresh(self):
        ctx = _make_async_ctx([], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "Start fresh" in result

    @pytest.mark.asyncio
    async def test_db_exception_returns_neutral_message(self):
        ctx = _make_async_ctx([], [], raise_exc=True)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "neutral" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_winning_trade_shows_win(self):
        """Profitable trade → string contains 'WIN +'"""
        trade = _mock_trade(entry_price=50000.0, exit_price=55000.0)  # +10%
        ctx = _make_async_ctx([trade], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "WIN +" in result

    @pytest.mark.asyncio
    async def test_losing_trade_shows_loss(self):
        """Losing trade → string contains 'LOSS'"""
        trade = _mock_trade(entry_price=50000.0, exit_price=48000.0)  # -4%
        ctx = _make_async_ctx([trade], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "LOSS" in result

    @pytest.mark.asyncio
    async def test_breakeven_trade_shows_breakeven(self):
        """Entry == exit → BREAKEVEN."""
        trade = _mock_trade(entry_price=50000.0, exit_price=50000.0)
        ctx = _make_async_ctx([trade], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "BREAKEVEN" in result

    @pytest.mark.asyncio
    async def test_result_contains_memory_header(self):
        trade = _mock_trade(entry_price=45000.0, exit_price=47000.0)
        ctx = _make_async_ctx([trade], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert "RECENT PERFORMANCE MEMORY" in result

    @pytest.mark.asyncio
    async def test_paper_trades_also_included(self):
        """Paper trades returned in second DB call are combined with live."""
        live = _mock_trade(entry_price=40000.0, exit_price=42000.0,
                           created_at=datetime(2026, 3, 10, 12, 0, 0))
        paper = _mock_trade(
            entry_price=30000.0, exit_price=28000.0,
            created_at=datetime(2026, 3, 10, 11, 0, 0)
        )
        ctx = _make_async_ctx([live], [paper], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        # Should have both trade outcomes in result
        assert "WIN +" in result
        assert "LOSS" in result

    @pytest.mark.asyncio
    async def test_returns_string(self):
        ctx = _make_async_ctx([], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_short_trade_pnl_computed(self):
        """For SHORT positions the PnL formula inverts the diff."""
        trade = _mock_trade(
            action="SHORT", side="SHORT",
            entry_price=50000.0, exit_price=45000.0,
        )
        ctx = _make_async_ctx([trade], [], raise_exc=False)
        with patch("backend.src.services.memory_manager.get_session", return_value=ctx):
            result = await fetch_recent_performance_memory()
        # Just verify it doesn't crash and returns a proper string
        assert isinstance(result, str)
        assert len(result) > 0
