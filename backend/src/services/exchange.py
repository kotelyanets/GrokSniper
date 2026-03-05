"""
exchange.py
-----------
Real trade execution via CCXT on Binance Testnet.
"""

import logging
import os
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "True").lower() == "true"

ALLOWED_COINS = ['USDT', 'BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB']

class CryptoExchange:
    """
    Handles interactions with the Binance exchange via CCXT.
    """
    def __init__(self):
        self._has_keys = bool(BINANCE_API_KEY and BINANCE_API_SECRET)
        self._dry_run = os.getenv("DRY_RUN", "False").lower() == "true"
        if not self._has_keys or self._dry_run:
            logger.warning("Simulation mode active (no keys or DRY_RUN=True). Trades will be simulated.")

    async def place_order(self, ticker: str, action: str, amount: float) -> dict:
        """
        Executes a real Market order on Binance (Testnet or Live).
        Returns execution details.
        """
        # --- Mock / DRY-RUN path ------------------------------------------------
        if not self._has_keys or self._dry_run:
            mock_price = 50000.0
            logger.info(f"[DRY-RUN] {action} {ticker} @ {mock_price} (mock)")
            return {
                "status": "success",
                "price": mock_price,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": True
            }

        # --- Real Path via CCXT -------------------------------------------------
        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        side = action.lower() # 'buy' or 'sell'
        
        # For SELL orders, we might need to fetch the balance to sell everything
        if side == "sell" and amount == 0:
            balance = await self.get_balance()
            amount = balance.get("assets", {}).get(ticker, 0.0)
            if amount == 0:
                logger.warning(f"Attempted to SELL {ticker} but balance is 0.")
                return {"status": "failed", "error": "Insufficient balance"}

        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
        })
        
        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)
            logger.info("CCXT: Sandbox mode enabled (Testnet).")

        try:
            logger.info(f"CCXT: Placing market {action} order for {amount} {symbol}")
            order = await exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount
            )
            
            price = order.get('average') or order.get('price') or 0.0
            filled = order.get('filled') or amount
            
            logger.info(f"[LIVE] Order filled @ {price}")
            
            return {
                "status": "success",
                "price": float(price),
                "amount": float(filled),
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "raw": order
            }

        except Exception as e:
            logger.error(f"CCXT Execution Failed: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "error": str(e)
            }
        finally:
            await exchange.close()

    async def get_balance(self) -> dict:
        """
        Fetches the current balance from Binance.
        Returns a dict with 'USDT' and other asset totals.
        """
        if not self._has_keys or self._dry_run:
            _initial = float(os.getenv("INITIAL_EQUITY", "1000.0"))
            return {"USDT": _initial, "BTC": 0.0, "total_usdt": _initial, "holdings": [], "dry_run": True}

        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
        })
        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)

        try:
            balance = await exchange.fetch_balance()
            usdt_total = balance.get('USDT', {}).get('total', 0.0)
            
            # Extract non-zero asset balances and calculate their USDT value
            assets_summary = []
            for currency, data in balance.items():
                if isinstance(data, dict) and data.get('total', 0) > 0:
                    amount = float(data['total'])
                    if currency not in ALLOWED_COINS or currency == 'USDT':
                        continue
                    
                    price = await self.get_price(currency)
                    assets_summary.append({
                        "coin": currency,
                        "amount": amount,
                        "value_usdt": amount * price
                    })
            
            return {
                "USDT": float(usdt_total),
                "holdings": assets_summary,
                "total_usdt": float(usdt_total) + sum(a["value_usdt"] for a in assets_summary),
                "dry_run": False
            }
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return {"USDT": 0.0, "total_usdt": 0.0, "error": str(e), "dry_run": False}
        finally:
            await exchange.close()

    async def get_free_balance(self, currency: str = 'USDT') -> float:
        """
        Fetches the current free (available) balance for a specific currency.
        Used for position sizing.
        """
        if not self._has_keys or self._dry_run:
            return float(os.getenv("INITIAL_EQUITY", "1000.0")) if currency == 'USDT' else 0.0

        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
        })
        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)

        try:
            balance = await exchange.fetch_balance()
            free_amount = balance.get(currency, {}).get('free', 0.0)
            return float(free_amount)
        except Exception as e:
            logger.error(f"Failed to fetch free balance for {currency}: {e}")
            return 0.0
        finally:
            await exchange.close()

    async def get_price(self, ticker: str) -> float:
        """Fetches the current market price for a ticker."""
        if not self._has_keys or self._dry_run:
            return 50000.0 # Mock price
        
        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
        })
        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)
        
        try:
            ticker_data = await exchange.fetch_ticker(symbol)
            return float(ticker_data.get('last') or 0.0)
        except ccxt.BadSymbol:
            # Silently ignore junk tokens from Testnet
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch price for {ticker}: {e}")
            return 0.0
        finally:
            await exchange.close()

    async def execute_trade(self, ticker: str, action: str, amount: float) -> dict:
        """Alias for compatibility with older engine code."""
        return await self.place_order(ticker, action, amount)

    async def get_top_tickers(self, limit: int = 20) -> list[str]:
        """
        Fetches the top N tickers by 24h volume from Binance.
        """
        if not self._has_keys or self._dry_run:
            return ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "SHIB", "DOT"]

        exchange = ccxt.binance({
            'enableRateLimit': True,
        })
        try:
            tickers = await exchange.fetch_tickers()
            # Sort by baseVolume (or quoteVolume)
            sorted_tickers = sorted(
                [t for t in tickers.values() if t['symbol'].endswith('/USDT')],
                key=lambda x: float(x.get('quoteVolume', 0)),
                reverse=True
            )
            return [t['symbol'].split('/')[0] for t in sorted_tickers[:limit]]
        except Exception as e:
            logger.error(f"Failed to fetch top tickers: {e}")
            return ["BTC", "ETH", "SOL"]
        finally:
            await exchange.close()

    async def get_technical_indicators(self, ticker: str, timeframe: str = '1h') -> dict:
        """
        Fetches OHLCV data on the 1h timeframe and calculates all elite strategy indicators:
        EMA_20, EMA_50, RSI_14, MACD (line + signal), Volume SMA_20, and raw candle OHLC.
        """
        if not self._has_keys or self._dry_run:
            return {
                "rsi": 50.0, "ema_20": 50000.0, "ema_50": 50000.0,
                "current_volume": 1000.0, "volume_sma_20": 500.0,
                "macd_line": 0.0, "macd_signal": 0.0,
                "prev_macd_line": 0.0, "prev_macd_signal": 0.0,
                "open": 50000.0, "high": 50000.0, "low": 50000.0, "close": 50000.0,
                "atr": 500.0,
            }

        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        exchange = ccxt.binance({
            'enableRateLimit': True,
        })
        if BINANCE_TESTNET:
            exchange.set_sandbox_mode(True)

        try:
            # Fetch 200 candles to ensure EMA_50 and EMA_200 have enough history
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=200)
            if not ohlcv:
                return {
                    "rsi": 50.0, "ema_20": 0.0, "ema_50": 0.0,
                    "current_volume": 0.0, "volume_sma_20": 0.0,
                    "macd_line": 0.0, "macd_signal": 0.0,
                    "prev_macd_line": 0.0, "prev_macd_signal": 0.0,
                    "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
                    "atr": 0.0,
                }

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
            # Calculate RSI (14)
            df['rsi'] = ta.rsi(df['close'], length=14)
            
            # Calculate EMA (20) and EMA (50)
            df['ema_20'] = ta.ema(df['close'], length=20)
            df['ema_50'] = ta.ema(df['close'], length=50)

            # Calculate Volume SMA (20) for volume spike detection
            df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
            
            # Calculate MACD
            macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
            if macd is not None and not macd.empty:
                df['macd_line'] = macd.iloc[:, 0]
                df['macd_signal'] = macd.iloc[:, 2]
            else:
                df['macd_line'] = 0.0
                df['macd_signal'] = 0.0

            # Calculate ATR (14) for dynamic stop-loss
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            return {
                "rsi":              float(latest['rsi'])          if pd.notna(latest['rsi'])          else 50.0,
                "ema_20":           float(latest['ema_20'])        if pd.notna(latest['ema_20'])        else 0.0,
                "ema_50":           float(latest['ema_50'])        if pd.notna(latest['ema_50'])        else 0.0,
                "current_volume":   float(latest['volume'])        if pd.notna(latest['volume'])        else 0.0,
                "volume_sma_20":    float(latest['volume_sma_20']) if pd.notna(latest['volume_sma_20']) else 0.0,
                "macd_line":        float(latest['macd_line'])     if pd.notna(latest['macd_line'])     else 0.0,
                "macd_signal":      float(latest['macd_signal'])   if pd.notna(latest['macd_signal'])   else 0.0,
                "prev_macd_line":   float(prev['macd_line'])       if pd.notna(prev['macd_line'])       else 0.0,
                "prev_macd_signal": float(prev['macd_signal'])     if pd.notna(prev['macd_signal'])     else 0.0,
                # Raw candle data for candlestick body confirmation
                "open":  float(latest['open'])  if pd.notna(latest['open'])  else 0.0,
                "high":  float(latest['high'])  if pd.notna(latest['high'])  else 0.0,
                "low":   float(latest['low'])   if pd.notna(latest['low'])   else 0.0,
                "close": float(latest['close']) if pd.notna(latest['close']) else 0.0,
                "atr":   float(latest['atr'])   if pd.notna(latest['atr'])   else 0.0,
            }

        except Exception as e:
            logger.error(f"Failed to fetch indicators for {ticker}: {e}")
            return {
                "rsi": 50.0, "ema_20": 0.0, "ema_50": 0.0,
                "current_volume": 0.0, "volume_sma_20": 0.0,
                "macd_line": 0.0, "macd_signal": 0.0,
                "prev_macd_line": 0.0, "prev_macd_signal": 0.0,
                "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
                "atr": 0.0,
            }
        finally:
            await exchange.close()

    async def is_btc_healthy(self) -> bool:
        """
        Returns True if BTC is in an uptrend (price > EMA_50).
        Used as a market regime filter for altcoin trades.
        """
        try:
            btc_price = await self.get_price('BTC')
            btc_ta = await self.get_technical_indicators('BTC')
            ema_50 = btc_ta.get('ema_50', 0.0)
            healthy = btc_price > ema_50
            logger.info(f"BTC Health Check: price={btc_price:.2f}, EMA50={ema_50:.2f}, healthy={healthy}")
            return healthy
        except Exception as e:
            logger.error(f"BTC health check failed: {e}")
            return True  # Default to True (permissive) on error to avoid blocking all trades
