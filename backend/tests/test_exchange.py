import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import ccxt.async_support as ccxt
import os

from backend.src.services.exchange import CryptoExchange

@pytest.fixture
def active_exchange(monkeypatch):
    """Fixture that forces CryptoExchange to use real mode (not dry-run)."""
    monkeypatch.setenv("BINANCE_API_KEY", "mock_key")
    monkeypatch.setenv("BINANCE_API_SECRET", "mock_secret")
    monkeypatch.setenv("DRY_RUN", "False")
    return CryptoExchange()

@pytest.fixture
def dry_run_exchange(monkeypatch):
    """Fixture that forces CryptoExchange to use dry-run mode."""
    monkeypatch.setenv("BINANCE_API_KEY", "mock_key")
    monkeypatch.setenv("BINANCE_API_SECRET", "mock_secret")
    monkeypatch.setenv("DRY_RUN", "True")
    return CryptoExchange()

@pytest.mark.asyncio
async def test_place_order_dry_run(dry_run_exchange):
    """Test place_order returns mock data in dry run mode."""
    with patch.object(dry_run_exchange, "get_price", new_callable=AsyncMock) as mock_price, \
         patch.object(dry_run_exchange, "_get_best_exchange_for_trade", new_callable=AsyncMock) as mock_route:
        mock_price.return_value = 50000.0
        mock_route.return_value = "binance"
        res = await dry_run_exchange.place_order("BTC", "BUY", 0.5)
        assert res["status"] == "success"
        assert res["price"] == 50000.0
        assert res["amount"] == 0.5
        assert res["dry_run"] is True

@pytest.mark.asyncio
async def test_place_order_live_success(active_exchange):
    """Test place_order success path simulating CCXT execution."""
    with patch("backend.src.services.exchange.ccxt.binance") as mock_binance:
        mock_instance = AsyncMock()
        mock_instance.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: str(amount))
        mock_binance.return_value = mock_instance
        
        # Mock CCXT create_order response
        mock_instance.create_order.return_value = {
            "id": "12345",
            "average": 65000.0,
            "filled": 0.5,
            "symbol": "BTC/USDT"
        }
        
        with patch.object(active_exchange, "_get_best_exchange_for_trade", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = "binance"
            res = await active_exchange.place_order("BTC", "BUY", 0.5)
            
            assert res["status"] == "success"
            assert res["price"] == 65000.0
            assert res["amount"] == 0.5
            assert res["dry_run"] is False
            mock_instance.close.assert_called_once()  # Ensure cleanup

@pytest.mark.asyncio
async def test_place_order_live_rate_limit(active_exchange):
    """Test place_order gracefully handles CCXT RateLimitExceeded."""
    with patch("backend.src.services.exchange.ccxt.binance") as mock_binance:
        mock_instance = AsyncMock()
        mock_instance.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: str(amount))
        mock_binance.return_value = mock_instance
        
        # Simulate rate limit error
        mock_instance.create_order.side_effect = ccxt.RateLimitExceeded("Too many requests")
        
        with patch.object(active_exchange, "_get_best_exchange_for_trade", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = "binance"
            res = await active_exchange.place_order("ETH", "SELL", 5.0)
            
            assert res["status"] == "failed"
            assert "Too many requests" in res["error"]
            assert res["dry_run"] is False
            mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_place_order_live_network_error(active_exchange):
    """Test place_order gracefully handles CCXT NetworkError."""
    with patch("backend.src.services.exchange.ccxt.binance") as mock_binance:
        mock_instance = AsyncMock()
        mock_instance.amount_to_precision = MagicMock(side_effect=lambda symbol, amount: str(amount))
        mock_binance.return_value = mock_instance
        
        # Simulate network error
        mock_instance.create_order.side_effect = ccxt.NetworkError("Connection reset by peer")
        
        with patch.object(active_exchange, "_get_best_exchange_for_trade", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = "binance"
            res = await active_exchange.place_order("SOL", "BUY", 10.0)
            
            assert res["status"] == "failed"
            assert "Connection reset by peer" in res["error"]
            assert res["dry_run"] is False
            mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_get_balance_live_success(active_exchange):
    """Test get_balance processes and sums holdings properly."""
    with patch("backend.src.services.exchange.ccxt.binance") as mock_binance:
        mock_instance = AsyncMock()
        mock_binance.return_value = mock_instance
        
        # Mock balance response
        mock_instance.fetch_balance.return_value = {
            "USDT": {"total": 1000.0, "free": 1000.0},
            "BTC": {"total": 0.5, "free": 0.5},
            "DOGE": {"total": 0.0, "free": 0.0}, # Should be ignored because 0
            "JUNK_COIN": {"total": 100.0, "free": 100.0} # Should be ignored (not in ALLOWED_COINS)
        }
        
        # Mock get_price to resolve asset value
        with patch.object(active_exchange, "get_price", new_callable=AsyncMock) as mock_get_price:
            mock_get_price.return_value = 60000.0 # BTC price
            
            res = await active_exchange.get_balance()
            
            assert res["USDT"] == 1000.0
            assert res["total_usdt"] == 1000.0 + (0.5 * 60000.0)
            assert len(res["holdings"]) == 1
            assert res["holdings"][0]["coin"] == "BTC"
            assert res["holdings"][0]["amount"] == 0.5
            assert res["holdings"][0]["value_usdt"] == 30000.0
            mock_instance.close.assert_called_once()

@pytest.mark.asyncio
async def test_get_top_tickers_live_success(active_exchange):
    """Test get_top_tickers sorts by quoteVolume and returns bases."""
    with patch("backend.src.services.exchange.ccxt.binance") as mock_binance:
        mock_instance = AsyncMock()
        mock_binance.return_value = mock_instance
        
        mock_instance.fetch_tickers.return_value = {
            "BTC/USDT": {"symbol": "BTC/USDT", "quoteVolume": 5000000},
            "ETH/USDT": {"symbol": "ETH/USDT", "quoteVolume": 3000000},
            "PEPE/USDT": {"symbol": "PEPE/USDT", "quoteVolume": 1000000},
            "ETH/BTC": {"symbol": "ETH/BTC", "quoteVolume": 8000000} # Ignored, not USDT
        }
        
        res = await active_exchange.get_top_tickers(limit=2)
        assert res == ["BTC", "ETH"]
        mock_instance.close.assert_called_once()
