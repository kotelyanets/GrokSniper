"""
exchange.py
-----------
Real trade execution via CCXT on Binance, Bybit, and OKX (Testnet or Live).
Incorporates a Smart Router that executes trades on the exchange offering the
best current order book spread for the specified ticker.
"""

import logging
import os
import asyncio
import ccxt.async_support as ccxt
from ccxt import InsufficientFunds, InvalidOrder, RateLimitExceeded, NetworkError, ExchangeError
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

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "True").lower() == "true"

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")
OKX_TESTNET = os.getenv("OKX_TESTNET", "True").lower() == "true"

ALLOWED_COINS = ['USDT', 'BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB', 'LINK']

class CryptoExchange:
    """
    Handles interactions with Binance, Bybit, and OKX via CCXT.
    Routes trades to the exchange with the best spread and aggregates portfolio balances.
    """
    def __init__(self):
        self._dry_run = os.getenv("DRY_RUN", "False").lower() == "true"
        self.active_keys = self._get_active_keys()
        self._has_keys = len(self.active_keys) > 0
        
        if not self._has_keys or self._dry_run:
            logger.warning("Simulation mode active (no keys or DRY_RUN=True). Trades will be simulated.")
        else:
            logger.info(f"Multi-Exchange Router Active. Connected keys: {', '.join(self.active_keys)}")

    def _get_active_keys(self) -> list:
        keys = []
        if BINANCE_API_KEY and BINANCE_API_SECRET: keys.append('binance')
        if BYBIT_API_KEY and BYBIT_API_SECRET: keys.append('bybit')
        if OKX_API_KEY and OKX_API_SECRET: keys.append('okx')
        return keys

    def _init_ccxt(self, ex_name: str, public_only: bool = False):
        """Instantiates a fresh CCXT instance for a specific exchange."""
        params = {'enableRateLimit': True}

        if ex_name == 'binance':
            if not public_only and 'binance' in self.active_keys:
                params.update({'apiKey': BINANCE_API_KEY, 'secret': BINANCE_API_SECRET})
            ex = ccxt.binance(params)
            # Explicitly set sandbox mode — avoid silent testnet when live key is set
            ex.set_sandbox_mode(BINANCE_TESTNET)
            if BINANCE_TESTNET:
                logger.debug("[exchange] Binance: TESTNET mode")
            else:
                logger.debug("[exchange] Binance: LIVE mode")
            return ex

        elif ex_name == 'bybit':
            if not public_only and 'bybit' in self.active_keys:
                params.update({'apiKey': BYBIT_API_KEY, 'secret': BYBIT_API_SECRET})
            ex = ccxt.bybit(params)
            ex.set_sandbox_mode(BYBIT_TESTNET)
            return ex

        elif ex_name == 'okx':
            if not public_only and 'okx' in self.active_keys:
                params.update({'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET})
                if OKX_PASSWORD: params['password'] = OKX_PASSWORD
            ex = ccxt.okx(params)
            ex.set_sandbox_mode(OKX_TESTNET)
            return ex

        return ccxt.binance(params)


    async def _get_best_exchange_for_trade(self, ticker: str, action: str) -> str:
        """
        Smart Routing: Checks orderbooks across active exchanges to find the best spread.
        If dry_run or no keys, checks all supported public exchanges just for simulation.
        Returns the exchange name ('binance', 'bybit', 'okx').
        """
        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        ex_to_check = self.active_keys if self.active_keys and not self._dry_run else ['binance', 'bybit', 'okx']
        
        if not ex_to_check:
            return 'binance'

        best_ex = ex_to_check[0]
        best_price = float('inf') if action.lower() == 'buy' else 0.0

        async def fetch_ob(ex_name):
            ex = self._init_ccxt(ex_name, public_only=True)
            try:
                ob = await ex.fetch_order_book(symbol, limit=5)
                # target price: lowest ask for buy, highest bid for sell
                price = ob['asks'][0][0] if action.lower() == 'buy' and ob['asks'] else None
                if action.lower() == 'sell':
                    price = ob['bids'][0][0] if ob['bids'] else None
                return ex_name, price
            except Exception:
                return ex_name, None
            finally:
                await ex.close()

        tasks = [fetch_ob(ex) for ex in ex_to_check]
        results = await asyncio.gather(*tasks)
        
        for ex_name, price in results:
            if price is not None:
                if action.lower() == 'buy' and price < best_price:
                    best_price = price
                    best_ex = ex_name
                elif action.lower() == 'sell' and price > best_price:
                    best_price = price
                    best_ex = ex_name

        if best_price not in (float('inf'), 0.0):
            logger.info(f"Smart Router: Selected {best_ex} for {action} {symbol} (Best Price: {best_price})")
        return best_ex

    async def place_order(self, ticker: str, action: str, amount: float) -> dict:
        """
        Executes a real Market order using the Smart Router (Testnet or Live).
        """
        if not self._has_keys or self._dry_run:
            mock_price = await self.get_price(ticker)
            if mock_price == 0.0:
                # Sensible fallbacks if oracle is down
                fallbacks = {"BTC": 96000.0, "ETH": 2600.0, "SOL": 185.0}
                mock_price = fallbacks.get(ticker.upper(), 10.0)
            target_ex_name = await self._get_best_exchange_for_trade(ticker, action)
            logger.info(f"[DRY-RUN] {action} {ticker} @ {mock_price} routed via {target_ex_name}")
            return {
                "status": "success",
                "price": mock_price,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": True,
                "exchange": target_ex_name
            }

        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        side = action.lower() # 'buy' or 'sell'
        
        target_ex_name = await self._get_best_exchange_for_trade(ticker, action)
        exchange = self._init_ccxt(target_ex_name)

        try:
            await exchange.load_markets()

            # Check balance if selling and amount is 0 (sell all)
            if side == "sell" and amount == 0:
                balance = await exchange.fetch_balance()
                currency = symbol.split('/')[0]
                amount = float(balance.get(currency, {}).get('free', 0.0))
                if amount == 0:
                    logger.warning(f"Attempted to SELL {ticker} on {target_ex_name} but free balance is 0.")
                    return {"status": "failed", "error": "Insufficient balance"}

            # Format amount using exchange.amount_to_precision
            amount = float(exchange.amount_to_precision(symbol, amount))
            if amount <= 0:
                logger.warning(f"Formatted amount is <= 0 for {symbol}: {amount}")
                return {"status": "failed", "error": "Amount rounded to zero by exchange precision rules"}

            logger.info(f"CCXT: Placing market {action} order for {amount} {symbol} on {target_ex_name.upper()}")
            order = await exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount
            )
            
            price = order.get('average') or order.get('price') or 0.0
            filled = order.get('filled') or amount
            
            logger.info(f"[LIVE] Order filled on {target_ex_name.upper()} @ {price}")
            
            return {
                "status": "success",
                "price": float(price),
                "amount": float(filled),
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "raw": order
            }

        except InsufficientFunds as e:
            logger.error(f"CCXT Insufficient Funds on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": f"InsufficientFunds: {e}"
            }
        except InvalidOrder as e:
            logger.error(f"CCXT Invalid Order on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": f"InvalidOrder: {e}"
            }
        except RateLimitExceeded as e:
            logger.error(f"CCXT Rate Limit Exceeded on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": f"RateLimitExceeded: {e}"
            }
        except NetworkError as e:
            logger.error(f"CCXT Network Error on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": f"NetworkError: {e}"
            }
        except ExchangeError as e:
            logger.error(f"CCXT Exchange Error on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": f"ExchangeError: {e}"
            }
        except Exception as e:
            logger.error(f"CCXT Execution Failed on {target_ex_name}: {e}")
            return {
                "status": "failed",
                "price": 0.0,
                "amount": amount,
                "ticker": ticker,
                "action": action,
                "dry_run": False,
                "exchange": target_ex_name,
                "error": str(e)
            }
        finally:
            await exchange.close()

    async def execute_trade(self, ticker: str, action: str, amount: float) -> dict:
        """Alias for compatibility."""
        return await self.place_order(ticker, action, amount)

    async def get_balance(self) -> dict:
        """
        Fetches the current portfolio balance aggregated across ALL active exchanges.
        Returns a master dict with 'USDT' and other asset totals.
        """
        if not self._has_keys or self._dry_run:
            _initial = float(os.getenv("INITIAL_EQUITY", "1000.0"))
            return {
                "USDT": _initial, 
                "total_usdt": _initial, 
                "holdings": [], 
                "dry_run": True, 
                "exchanges_breakdown": {}
            }

        master_usdt = 0.0
        master_holdings_map = {}
        exchanges_breakdown = {}

        async def fetch_ex_balance(ex_name):
            ex = self._init_ccxt(ex_name)
            try:
                bal = await ex.fetch_balance()
                return ex_name, bal
            except Exception as e:
                logger.error(f"Failed to fetch balance from {ex_name}: {e}")
                return ex_name, {}
            finally:
                await ex.close()

        tasks = [fetch_ex_balance(en) for en in self.active_keys]
        results = await asyncio.gather(*tasks)

        for ex_name, bal in results:
            if not bal: continue
            
            usdt_bal = float(bal.get('USDT', {}).get('total', 0.0))
            master_usdt += usdt_bal
            exchanges_breakdown[ex_name] = {"USDT": usdt_bal, "assets": []}
            
            for currency, data in bal.items():
                if isinstance(data, dict) and data.get('total', 0) > 0:
                    amount = float(data['total'])
                    if currency not in ALLOWED_COINS or currency == 'USDT':
                        continue
                    
                    if currency not in master_holdings_map:
                        master_holdings_map[currency] = 0.0
                    master_holdings_map[currency] += amount
                    exchanges_breakdown[ex_name]["assets"].append({"coin": currency, "amount": amount})

        # Calculate USDT value of aggregated holdings
        assets_summary = []
        total_value_usdt = master_usdt

        for currency, amount in master_holdings_map.items():
            price = await self.get_price(currency)
            val = amount * price
            assets_summary.append({
                "coin": currency,
                "amount": amount,
                "value_usdt": val
            })
            total_value_usdt += val

        return {
            "USDT": master_usdt,
            "holdings": assets_summary,
            "total_usdt": total_value_usdt,
            "dry_run": False,
            "exchanges_breakdown": exchanges_breakdown
        }

    async def get_free_balance(self, currency: str = 'USDT') -> float:
        """Fetches the aggregated total free balance across all active exchanges."""
        if not self._has_keys or self._dry_run:
            return float(os.getenv("INITIAL_EQUITY", "1000.0")) if currency == 'USDT' else 0.0

        total_free = 0.0
        async def fetch_free(ex_name):
            ex = self._init_ccxt(ex_name)
            try:
                bal = await ex.fetch_balance()
                return float(bal.get(currency, {}).get('free', 0.0))
            except Exception:
                return 0.0
            finally:
                await ex.close()

        tasks = [fetch_free(en) for en in self.active_keys]
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def get_price(self, ticker: str) -> float:
        """Fetches the current market price using Binance as the primary oracle."""
        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        
        ex = self._init_ccxt('binance', public_only=True)
        try:
            ticker_data = await ex.fetch_ticker(symbol)
            return float(ticker_data.get('last') or 0.0)
        except ccxt.BadSymbol:
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch price for {ticker}: {e}")
            return 0.0
        finally:
            await ex.close()

    async def get_top_tickers(self, limit: int = 20) -> list[str]:
        """Fetches the top N tickers by volume from Binance oracle."""
        ex = self._init_ccxt('binance', public_only=True)
        try:
            tickers = await ex.fetch_tickers()
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
            await ex.close()

    async def get_technical_indicators(self, ticker: str, timeframe: str = '1h') -> dict:
        """
        Fetches OHLCV data from Binance Oracle and calculates indicators.
        """
        symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
        ex = self._init_ccxt('binance', public_only=True)

        try:
            ohlcv = await ex.fetch_ohlcv(symbol, timeframe, limit=200)
            if not ohlcv:
                raise Exception("Empty OHLCV data")
                
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema_20'] = ta.ema(df['close'], length=20)
            df['ema_50'] = ta.ema(df['close'], length=50)
            df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
            
            macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
            if macd is not None and not macd.empty:
                df['macd_line'] = macd.iloc[:, 0]
                df['macd_signal'] = macd.iloc[:, 2]
            else:
                df['macd_line'] = 0.0
                df['macd_signal'] = 0.0

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
            await ex.close()

    async def is_btc_healthy(self) -> bool:
        """Returns True if BTC is in an uptrend (price > EMA_50)."""
        try:
            btc_price = await self.get_price('BTC')
            btc_ta = await self.get_technical_indicators('BTC')
            ema_50 = btc_ta.get('ema_50', 0.0)
            return btc_price > ema_50
        except Exception:
            return True

    async def is_btc_dumping(self) -> bool:
        """Returns True if BTC dropped > 1.5% in the last hour."""
        ex = self._init_ccxt('binance', public_only=True)
        try:
            ohlcv = await ex.fetch_ohlcv("BTC/USDT", "1h", limit=2)
            if not ohlcv or len(ohlcv) < 2: return False
            c_open, c_close = ohlcv[-1][1], ohlcv[-1][4]
            return ((c_open - c_close) / c_open) * 100 > 1.5
        except Exception:
            return False
        finally:
            await ex.close()
