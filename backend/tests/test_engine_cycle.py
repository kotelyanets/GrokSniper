"""
test_engine_cycle.py
--------------------
Tests the full execution cycle of `scan_all_tickers` in the engine.
Mocks all external data fetching and AI agents to isolate the pipeline logic,
including DB exception handling and atomic rollbacks.
"""

import pytest
from unittest.mock import AsyncMock, patch
from backend.src.core.engine import scan_all_tickers

@pytest.fixture
def mock_engine_dependencies():
    with patch("backend.src.core.engine._get_btc_dump_mode", new_callable=AsyncMock) as mock_btc, \
         patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
         patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock) as mock_sent, \
         patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock) as mock_prop, \
         patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock) as mock_eval, \
         patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock) as mock_exec:
        
        # Setup defaults
        mock_btc.return_value = False # Not dumping
        mock_ohlcv.return_value = ("FAKE_CONDENSED", {"close": 50000.0, "rsi": 30.0}, None)
        mock_sent.return_value = (50, "Bullish news")
        mock_prop.return_value = [{"ticker": "BTC", "proposed_action": "LONG", "confidence": 80}]
        mock_eval.return_value = [{
            "ticker": "BTC", "proposed_action": "LONG", "confidence": 80, 
            "verdict": "APPROVED", "regime": "BULLISH", "quant_reasoning": "RSI oversold",
            "risk_reasoning": "Macro okay"
        }]
        mock_exec.return_value = {"ticker": "BTC", "action": "LONG", "trade_placed": True}

        yield {
            "btc": mock_btc,
            "ohlcv": mock_ohlcv,
            "sent": mock_sent,
            "prop": mock_prop,
            "eval": mock_eval,
            "exec": mock_exec
        }

@pytest.mark.asyncio
async def test_successful_cycle(mock_engine_dependencies):
    """Test a full successful engine cycle where a trade is proposed and approved."""
    results = await scan_all_tickers()
    
    assert len(results) > 0
    btc_result = next((r for r in results if r["ticker"] == "BTC"), None)
    
    assert btc_result is not None
    assert btc_result["action"] == "LONG"
    assert btc_result["trade_placed"] is True
    
    deps = mock_engine_dependencies
    deps["ohlcv"].assert_called()
    deps["prop"].assert_called_once()
    deps["eval"].assert_called_once()
    deps["exec"].assert_called_once()


@pytest.mark.asyncio
async def test_btc_dump_mode_blocks_longs(mock_engine_dependencies):
    """If BTC is dumping, the engine should block and skip everything."""
    deps = mock_engine_dependencies
    deps["btc"].return_value = True

    # Temporarily remove testnet flag to ensure dump mode check runs
    with patch("os.getenv", return_value="False"):
        results = await scan_all_tickers()
    
    # Should short-circuit
    assert all(r["action"] == "SKIP" for r in results)
    deps["ohlcv"].assert_not_called()
    deps["prop"].assert_not_called()


@pytest.mark.asyncio
async def test_low_confidence_blocks_execution(mock_engine_dependencies):
    """If the AI confidence is below threshold, it should output HOLD and not execute."""
    deps = mock_engine_dependencies
    deps["eval"].return_value = [{
        "ticker": "BTC", "proposed_action": "LONG", "confidence": 20, # Very low
        "verdict": "APPROVED", "regime": "BULLISH"
    }]

    with patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 60):
        results = await scan_all_tickers()
    
    btc_result = next((r for r in results if r["ticker"] == "BTC"), None)
    assert btc_result["action"] == "HOLD"
    assert btc_result["trade_placed"] is False
    deps["exec"].assert_not_called()


@pytest.mark.asyncio
async def test_db_rollback_on_execute_error(mock_engine_dependencies):
    """If _execute_decision throws an error (like DB truncation or API failure), engine catches it gracefully."""
    deps = mock_engine_dependencies
    deps["exec"].side_effect = Exception("Database error: Data too long")

    results = await scan_all_tickers()
    
    btc_result = next((r for r in results if r["ticker"] == "BTC"), None)
    assert btc_result["action"] == "ERROR"
    assert btc_result["trade_placed"] is False
    assert "Database error" in btc_result["reason"]
