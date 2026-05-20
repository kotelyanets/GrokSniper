"""
test_position_lifecycle.py
--------------------------
Integration tests for the full open-to-close position lifecycle.
Verifies Phase 8 (Paper Closer) logic and orphan detection.
"""

import pytest
import asyncio
from sqlalchemy import select, text
from datetime import datetime, timezone, timedelta

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import PaperTrade, Trade
from backend.src.services.paper_trade_closer import _check_and_close_trade, detect_orphan_trades

# Mock dependencies
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
async def cleanup_db_engine():
    """Dispose of global engine before and after every test to clear the pool locally."""
    try:
        from backend.src.db.database import engine
        await engine.dispose()
    except Exception:
        pass
    yield
    try:
        from backend.src.db.database import engine
        await engine.dispose()
    except Exception:
        pass


class TestPositionLifecycle:

    @pytest.fixture
    async def db_session(self):
        async with AsyncSessionLocal() as session:
            yield session

    @pytest.mark.asyncio
    async def test_paper_trade_long_hits_take_profit(self, db_session):
        # 1. Setup mock trade in DB
        trade = PaperTrade(
            ticker="MOCK_L",
            action="LONG",
            entry_price=100.0,
            size_usdt=1000.0,
            stop_loss=90.0,
            take_profit=110.0,
            status="OPEN"
        )
        db_session.add(trade)
        await db_session.commit()

        # 2. Trigger closer with price hitting TP
        closed = await _check_and_close_trade(trade, 115.0)

        # 3. Verify
        assert closed is True
        
        await db_session.refresh(trade)
        assert trade.status == "CLOSED"
        assert trade.exit_price == 110.0
        assert trade.pnl_usdt > 0

    @pytest.mark.asyncio
    async def test_paper_trade_short_hits_stop_loss(self, db_session):
        trade = PaperTrade(
            ticker="MOCK_S",
            action="SHORT",
            entry_price=100.0,
            size_usdt=500.0,
            stop_loss=105.0,
            take_profit=90.0,
            status="OPEN"
        )
        db_session.add(trade)
        await db_session.commit()

        # Price goes up, hitting SL for a short
        closed = await _check_and_close_trade(trade, 110.0)

        assert closed is True
        await db_session.refresh(trade)
        assert trade.status == "CLOSED"
        assert trade.exit_price == 105.0
        assert trade.pnl_usdt < 0

    @pytest.mark.asyncio
    async def test_paper_trade_stays_open_inside_range(self, db_session):
        trade = PaperTrade(
            ticker="MOCK_O",
            action="LONG",
            entry_price=100.0,
            size_usdt=1000.0,
            stop_loss=90.0,
            take_profit=110.0,
            status="OPEN"
        )
        db_session.add(trade)
        await db_session.commit()

        closed = await _check_and_close_trade(trade, 105.0)

        assert closed is False
        await db_session.refresh(trade)
        assert trade.status == "OPEN"
        assert trade.exit_price is None

    @pytest.mark.asyncio
    async def test_detect_orphan_trades(self, db_session):
        # Create a valid trade
        valid_trade = PaperTrade(
            ticker="VAL", action="LONG", entry_price=10.0, size_usdt=100.0,
            stop_loss=9.0, take_profit=11.0, status="OPEN"
        )
        db_session.add(valid_trade)
        
        # Create a trade with no SL/TP (infinite orphan)
        orphan_no_sl = PaperTrade(
            ticker="ORP1", action="LONG", entry_price=10.0, size_usdt=100.0,
            stop_loss=0.0, take_profit=0.0, status="OPEN"
        )
        db_session.add(orphan_no_sl)
        
        await db_session.commit()
        
        # Override created_at for an age-based orphan
        old_trade = PaperTrade(
            ticker="ORP2", action="SHORT", entry_price=10.0, size_usdt=100.0,
            stop_loss=11.0, take_profit=9.0, status="OPEN"
        )
        db_session.add(old_trade)
        await db_session.commit()

        # Manually backdate ORP2 to 3 days ago
        old_date = datetime.now(timezone.utc) - timedelta(days=3)
        await db_session.execute(
            text(f"UPDATE paper_trades SET created_at = '{old_date.isoformat()}' WHERE id = '{old_trade.id}'")
        )
        await db_session.commit()

        orphans = await detect_orphan_trades()

        assert any("ORP1" in o for o in orphans)
        assert any("ORP2" in o for o in orphans)
        assert not any("VAL" in o for o in orphans)
