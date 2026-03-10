import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal
import asyncio

from backend.src.services.ws_manager import (
    _close_position,
    _watch_trade,
    cancel_all_watchers,
    _active_watchers
)
from backend.src.db.models import Trade
import os

@pytest.fixture
def mock_db_trade():
    """Returns a basic mocked Trade object."""
    t = Trade(
        id="test-trade-123",
        ticker="BTC",
        action="BUY",
        amount=Decimal("0.1"),
        price=Decimal("50000.0"),
        status="success",
        is_closed=False,
        side="LONG",
        highest_price=Decimal("50000.0"),
        lowest_price=Decimal("50000.0"),
        stop_loss_price=Decimal("48500.0")
    )
    return t

@pytest.mark.asyncio
async def test_close_position_long_success(mock_db_trade):
    """Test closing a LONG position updates DB and sends Telegram alert."""
    with patch("backend.src.services.ws_manager.AsyncSessionLocal") as mock_session, \
         patch("backend.src.services.ws_manager._exchange") as mock_exchange, \
         patch("backend.src.services.ws_manager.send_exit_alert") as mock_alert, \
         patch.dict(os.environ, {"PAPER_TRADE": "False"}):
         
        # Make the exchange return a successful market SELL order
        mock_exchange.place_order = AsyncMock(return_value={
            "status": "success",
            "price": 55000.0,
            "amount": 0.1
        })
        
        # Mock DB session execution
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_trade
        mock_session_instance.execute = AsyncMock(return_value=mock_result)
        mock_session_instance.commit = AsyncMock()
        
        await _close_position(
            trade=mock_db_trade,
            exit_reason="take_profit",
            exit_label="Hit TP",
            entry_price=50000.0,
            highest_price=55500.0,
            side="LONG",
        )
        
        mock_exchange.place_order.assert_called_once_with(
            ticker="BTC", action="SELL", amount=0
        )
        assert mock_db_trade.is_closed is True
        mock_session_instance.commit.assert_called_once()
        mock_alert.assert_called_once()

@pytest.mark.asyncio
async def test_close_position_short_paper_trade(mock_db_trade):
    """Test closing a SHORT position in paper mode skips real exchange execution."""
    mock_db_trade.side = "SHORT"
    with patch("backend.src.services.ws_manager.AsyncSessionLocal") as mock_session, \
         patch("backend.src.services.ws_manager._exchange") as mock_exchange, \
         patch("backend.src.services.ws_manager.send_exit_alert") as mock_alert, \
         patch.dict(os.environ, {"PAPER_TRADE": "True"}):
         
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_trade
        mock_session_instance.execute = AsyncMock(return_value=mock_result)
        mock_session_instance.commit = AsyncMock()
        
        await _close_position(
            trade=mock_db_trade,
            exit_reason="hard_stop",
            exit_label="Hit SL",
            entry_price=50000.0,
            highest_price=51000.0,
            side="SHORT",
            lowest_price=50000.0
        )
        
        # Should NOT call exchange because PAPER_TRADE is True
        mock_exchange.place_order.assert_not_called()
        assert mock_db_trade.is_closed is True
        mock_alert.assert_called_once()

@pytest.mark.asyncio
async def test_watch_trade_long_hard_stop(mock_db_trade):
    """Test that a WebSocket stream triggering SL closes the trade immediately."""
    
    # Fake WebSocket stream yielding a single dropping price that triggers SL
    class FakeWS:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def __aiter__(self):
            # Price drops far below SL (48500.0)
            yield '{"p":"48000.0"}'

    with patch("backend.src.services.ws_manager.AsyncSessionLocal") as mock_session, \
         patch("backend.src.services.ws_manager.websockets.connect", return_value=FakeWS()), \
         patch("backend.src.services.ws_manager._close_position", new_callable=AsyncMock) as mock_close:
         
        mock_session_instance = mock_session.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_trade
        mock_session_instance.execute = AsyncMock(return_value=mock_result)
        
        # Register the trade in watchers just in case
        _active_watchers["test-trade-123"] = asyncio.current_task()
        
        await _watch_trade("test-trade-123")
        
        # It should detect SL trigger and call _close_position
        mock_close.assert_called_once()
        kwargs = mock_close.call_args.kwargs
        assert kwargs["exit_reason"] == "hard_stop"
        assert kwargs["side"] == "LONG"
        
        # Should be removed from watcher pool
        assert "test-trade-123" not in _active_watchers

@pytest.mark.asyncio
async def test_cancel_all_watchers():
    """Test watcher cleanup clears dictionary safely."""
    mock_task = MagicMock()
    _active_watchers["test-1"] = mock_task
    _active_watchers["test-2"] = mock_task
    
    cancel_all_watchers()
    
    assert len(_active_watchers) == 0
    assert mock_task.cancel.call_count == 2
