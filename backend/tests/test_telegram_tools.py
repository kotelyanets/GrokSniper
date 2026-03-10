import pytest
from unittest.mock import AsyncMock, patch
from backend.src.agents.trading_tools import get_account_summary, close_all_positions, request_on_demand_analysis

@pytest.mark.asyncio
async def test_get_account_summary_empty():
    """Test get_account_summary with no open trades"""
    with patch("backend.src.agents.trading_tools.CryptoExchange") as MockExchange:
        mock_exchange = MockExchange.return_value
        mock_exchange.get_balance = AsyncMock(return_value={"total_usdt": 1250.50})
        
        with patch("backend.src.agents.trading_tools.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__.return_value.execute = AsyncMock(return_value=AsyncMock(scalars=lambda: AsyncMock(all=lambda: [])))
            
            result = await get_account_summary()
            assert "1,250.50 USDT" in result
            assert "No real positions open" in result

@pytest.mark.asyncio
async def test_close_all_positions(monkeypatch):
    """Test emergency panic close"""
    import backend.src.config as config
    config.TRADING_PAUSED = False
    
    class MockTrade:
        def __init__(self, t, s, a):
            self.ticker = t
            self.side = s
            self.amount = a
            self.is_closed = False
            
    class MockPaperTrade:
        def __init__(self):
            self.status = "OPEN"
            
    mock_real = [MockTrade("BTC", "LONG", 0.1), MockTrade("ETH", "SHORT", 1.5)]
    mock_paper = [MockPaperTrade()]

    # Mock the DB queries dynamically
    async def mock_execute(stmt):
        str_stmt = str(stmt).lower()
        ret_data = mock_paper if "paper_trade" in str_stmt else mock_real
        
        class ScalarWrapper:
            def all(self):
                return ret_data
                
        class ResultWrapper:
            def scalars(self):
                return ScalarWrapper()
                
        return ResultWrapper()
            
    with patch("backend.src.agents.trading_tools.CryptoExchange") as MockExchange:
        mock_exchange = MockExchange.return_value
        mock_exchange.execute_trade = AsyncMock(return_value={"status": "success"})
        
        with patch("backend.src.agents.trading_tools.AsyncSessionLocal") as mock_session:
            mock_session_instance = mock_session.return_value.__aenter__.return_value
            mock_session_instance.execute = AsyncMock(side_effect=mock_execute)
            mock_session_instance.commit = AsyncMock()
            
            result = await close_all_positions()
            
            assert "PANIC SUCCESS" in result
            assert "Closed 3 positions" in result
            assert config.TRADING_PAUSED == True
            assert mock_real[0].is_closed == True
            assert mock_paper[0].status == "CLOSED"

@pytest.mark.asyncio
async def test_request_on_demand_analysis():
    """Test specific on-demand BOARD analysis via Telegram"""
    with patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv") as mock_ohlcv, \
         patch("backend.src.core.engine._groq_sentiment") as mock_sent, \
         patch("backend.src.services.memory_manager.fetch_recent_performance_memory") as mock_mem, \
         patch("backend.src.core.agents.quant_analyst.propose_trades") as mock_prop, \
         patch("backend.src.core.agents.risk_guardian.evaluate_proposals") as mock_eval:
         
        mock_ohlcv.return_value = ("condensed_data", {}, {})
        mock_sent.return_value = (85, "Bullish")
        mock_mem.return_value = "No recent losses."
        
        mock_prop.return_value = [{
            "ticker": "SOL",
            "proposed_action": "LONG",
            "confidence": 95,
            "position_size_pct": 5,
            "quant_reasoning": "Strong setup"
        }]
        
        mock_eval.return_value = [{
            "ticker": "SOL",
            "proposed_action": "LONG",
            "confidence": 95,
            "verdict": "APPROVED",
            "risk_reasoning": "Risk is acceptable"
        }]
        
        result = await request_on_demand_analysis("SOL")
        
        assert "Board of Directors Analysis: SOL" in result
        assert "APPROVED" in result
        assert "LONG (95%)" in result
        assert "Risk is acceptable" in result
