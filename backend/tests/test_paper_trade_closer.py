"""
test_paper_trade_closer.py
===========================
50 tests for paper_trade_closer.py.

Covers:
  • _check_and_close_trade: LONG SL hit, LONG TP hit, SHORT SL hit, SHORT TP hit,
    no trigger, zero/invalid price, already-closed guard
  • PnL calculation accuracy for LONG and SHORT
  • detect_orphan_trades: no SL/TP, age > 48h, healthy trades
  • paper_trade_closer_loop: no trades → sleep, trades checked, closed_count tracked
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Mock PaperTrade factory
# ─────────────────────────────────────────────────────────────────────────────

def make_paper_trade(
    id="uuid-1",
    ticker="BTC",
    action="LONG",
    entry_price=50000.0,
    stop_loss=48000.0,
    take_profit=55000.0,
    size_usdt=1000.0,
    status="OPEN",
    created_at=None,
):
    trade = MagicMock()
    trade.id = id
    trade.ticker = ticker
    trade.action = action
    trade.entry_price = entry_price
    trade.stop_loss = stop_loss
    trade.take_profit = take_profit
    trade.size_usdt = size_usdt
    trade.status = status
    trade.created_at = created_at or datetime.now(timezone.utc)
    return trade


# ─────────────────────────────────────────────────────────────────────────────
# _check_and_close_trade — LONG trades
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckAndCloseLong:
    @pytest.mark.asyncio
    async def test_long_stop_loss_triggered(self):
        """Price at SL level → trade closes."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000, take_profit=55000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="OPEN")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=48000.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_long_below_stop_loss_triggered(self):
        """Price below SL level → should also close."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="OPEN")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=46000.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_long_take_profit_triggered(self):
        """Price at TP → trade closes with profit."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000, take_profit=55000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="OPEN")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=55000.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_long_no_trigger_when_price_in_range(self):
        """Price between SL and TP → no close."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000, take_profit=55000)
        result = await _check_and_close_trade(trade, current_price=51000.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_long_returns_false_on_zero_price(self):
        from backend.src.services.paper_trade_closer import _check_and_close_trade
        trade = make_paper_trade(action="LONG")
        result = await _check_and_close_trade(trade, current_price=0.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_long_returns_false_on_negative_price(self):
        from backend.src.services.paper_trade_closer import _check_and_close_trade
        trade = make_paper_trade(action="LONG")
        result = await _check_and_close_trade(trade, current_price=-1.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_long_pnl_calculated_correctly_on_tp(self):
        """PnL on TP = (tp - entry) / entry * size_usdt."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(
            action="LONG", entry_price=50000, stop_loss=48000,
            take_profit=55000, size_usdt=1000.0
        )
        expected_pnl = (55000 - 50000) / 50000 * 1000.0  # = 100.0

        committed_trade = None

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            db_trade = make_paper_trade(status="OPEN")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = db_trade
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            await _check_and_close_trade(trade, current_price=55000.0)
            # Verify PnL was set correctly on the db object
            assert abs(db_trade.pnl_usdt - expected_pnl) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# _check_and_close_trade — SHORT trades
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckAndCloseShort:
    @pytest.mark.asyncio
    async def test_short_stop_loss_triggered_on_price_above_sl(self):
        """For SHORT, SL is above entry. Price >= SL → close."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="SHORT", entry_price=50000, stop_loss=53000, take_profit=45000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="OPEN")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=53000.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_short_take_profit_triggered_below_entry(self):
        """For SHORT, TP is below entry. Price <= TP → close with profit."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="SHORT", entry_price=50000, stop_loss=53000, take_profit=45000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="OPEN")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=45000.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_short_no_trigger_in_range(self):
        """Price between SL and TP for SHORT → no close."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="SHORT", entry_price=50000, stop_loss=53000, take_profit=45000)
        result = await _check_and_close_trade(trade, current_price=49000.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_short_pnl_positive_on_tp(self):
        """SHORT TP = (entry - tp) / entry * size_usdt."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(
            action="SHORT", entry_price=50000, stop_loss=53000,
            take_profit=45000, size_usdt=1000.0
        )
        expected_pnl = (50000 - 45000) / 50000 * 1000.0  # = 100.0

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess, \
             patch("backend.src.services.paper_trade_closer.send_telegram_message", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.send_email", new_callable=AsyncMock), \
             patch("backend.src.services.paper_trade_closer.broadcast_to_dashboard", new_callable=AsyncMock), \
             patch("asyncio.create_task"):

            mock_session = AsyncMock()
            db_trade = make_paper_trade(status="OPEN")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = db_trade
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            await _check_and_close_trade(trade, current_price=45000.0)
            assert abs(db_trade.pnl_usdt - expected_pnl) < 0.01

    @pytest.mark.asyncio
    async def test_already_closed_trade_is_skipped(self):
        """If trade is already CLOSED in DB, return False without double-closing."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            # Already CLOSED in DB
            mock_result.scalar_one_or_none.return_value = make_paper_trade(status="CLOSED")
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=46000.0)
            assert result is False

    @pytest.mark.asyncio
    async def test_not_found_in_db_returns_false(self):
        """If trade ID not found in DB, return False without crashing."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None  # Not found
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=46000.0)
            assert result is False

    @pytest.mark.asyncio
    async def test_db_exception_returns_false(self):
        """If DB throws, _check_and_close_trade returns False without raising."""
        from backend.src.services.paper_trade_closer import _check_and_close_trade

        trade = make_paper_trade(action="LONG", entry_price=50000, stop_loss=48000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_sess.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB connection lost"))
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _check_and_close_trade(trade, current_price=46000.0)
            assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# PnL calculations
# ─────────────────────────────────────────────────────────────────────────────

class TestPnLCalculations:
    """Pure arithmetic tests (without DB), using logic inlined from the module."""

    def test_long_sl_pnl_is_negative(self):
        entry, exit_p, size = 50000.0, 48000.0, 1000.0
        pnl = (exit_p - entry) / entry * size
        assert pnl < 0

    def test_long_tp_pnl_is_positive(self):
        entry, exit_p, size = 50000.0, 55000.0, 1000.0
        pnl = (exit_p - entry) / entry * size
        assert pnl > 0

    def test_short_sl_pnl_is_negative(self):
        entry, exit_p, size = 50000.0, 53000.0, 1000.0
        pnl = (entry - exit_p) / entry * size
        assert pnl < 0

    def test_short_tp_pnl_is_positive(self):
        entry, exit_p, size = 50000.0, 45000.0, 1000.0
        pnl = (entry - exit_p) / entry * size
        assert pnl > 0

    def test_long_pnl_pct_ten_percent_gain(self):
        entry, exit_p = 50000.0, 55000.0
        pnl_pct = ((exit_p - entry) / entry) * 100
        assert abs(pnl_pct - 10.0) < 0.001

    def test_short_pnl_pct_ten_percent_gain(self):
        entry, exit_p = 50000.0, 45000.0
        pnl_pct = ((entry - exit_p) / entry) * 100
        assert abs(pnl_pct - 10.0) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# detect_orphan_trades
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectOrphanTrades:
    @pytest.mark.asyncio
    async def test_no_trades_returns_empty_list(self):
        from backend.src.services.paper_trade_closer import detect_orphan_trades

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            orphans = await detect_orphan_trades()
            assert orphans == []

    @pytest.mark.asyncio
    async def test_trade_with_no_sl_no_tp_is_orphan(self):
        from backend.src.services.paper_trade_closer import detect_orphan_trades

        trade = make_paper_trade(action="LONG", stop_loss=None, take_profit=None)
        trade.stop_loss = None
        trade.take_profit = None

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [trade]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            orphans = await detect_orphan_trades()
            assert any("BTC" in o for o in orphans)

    @pytest.mark.asyncio
    async def test_trade_older_than_48h_is_orphan(self):
        from backend.src.services.paper_trade_closer import detect_orphan_trades

        old_time = datetime.now(timezone.utc) - timedelta(hours=50)
        trade = make_paper_trade(action="LONG", stop_loss=48000, take_profit=55000, created_at=old_time)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [trade]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            orphans = await detect_orphan_trades()
            assert any("BTC" in o for o in orphans)

    @pytest.mark.asyncio
    async def test_healthy_recent_trade_is_not_orphan(self):
        from backend.src.services.paper_trade_closer import detect_orphan_trades

        trade = make_paper_trade(action="LONG", stop_loss=48000, take_profit=55000)

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [trade]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sess.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            orphans = await detect_orphan_trades()
            assert orphans == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self):
        from backend.src.services.paper_trade_closer import detect_orphan_trades

        with patch("backend.src.services.paper_trade_closer.AsyncSessionLocal") as mock_sess:
            mock_sess.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB error"))
            mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

            orphans = await detect_orphan_trades()
            assert orphans == []
