import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta

# Simple in-memory cache to prevent fetching the same datasets repeatedly when the user
# simply adjust hyperparameters in the UI.
# Structure: { "BTC/USDT_1h_30": {"df": pd.DataFrame, "timestamp_fetched": float} }
_OHLCV_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour cache validity

async def fetch_historical_data_cached(
    symbol: str,
    timeframe: str,
    days_back: int,
) -> pd.DataFrame:
    cache_key = f"{symbol}_{timeframe}_{days_back}"
    now_ts = time.time()
    
    # Check cache
    if cache_key in _OHLCV_CACHE:
        cached = _OHLCV_CACHE[cache_key]
        if now_ts - cached["timestamp_fetched"] < CACHE_TTL_SECONDS:
            return cached["df"].copy()

    # Need to fetch
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)
    batch_size = 1000
    all_ohlcv = []
    fetch_since = since_ms
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        while True:
            candles = await exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=fetch_since, limit=batch_size
            )
            if not candles:
                break
            all_ohlcv.extend(candles)
            last_ts = candles[-1][0]
            if len(candles) < batch_size or last_ts >= now_ms:
                break
            fetch_since = last_ts + 1
            await asyncio.sleep(0.05) # Be kind to rate limits
    finally:
        await exchange.close()

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df.drop_duplicates(subset="timestamp", inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # TA indicators required by Golden Strategy
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()
    df.dropna(inplace=True)
    
    # Save to cache
    _OHLCV_CACHE[cache_key] = {"df": df.copy(), "timestamp_fetched": now_ts}
    
    return df

def run_backtest_sim(df: pd.DataFrame, params: dict, initial_balance: float = 1000.0) -> dict:
    """
    params keys:
      hard_stop           (float) e.g. 0.97
      trailing_activation (float) e.g. 1.03  
      trailing_distance   (float) e.g. 0.985 
      take_profit         (float) e.g. 1.08  
    """
    hard_stop           = params.get("hard_stop", 0.97)
    trailing_activation = params.get("trailing_activation", 1.03)
    trailing_distance   = params.get("trailing_distance", 0.985)
    take_profit         = params.get("take_profit", 1.08)

    balance       = initial_balance
    position      = 0.0
    entry_price   = 0.0
    highest_price = 0.0
    
    trades_history = []
    equity_curve = []

    MACD_COL    = "MACD_12_26_9"
    SIGNAL_COL  = "MACDs_12_26_9"
    EMA20_COL   = "EMA_20"
    EMA50_COL   = "EMA_50"
    RSI_COL     = "RSI_14"
    VOL_SMA_COL = "VOL_SMA_20"

    peak_balance = initial_balance
    max_drawdown = 0.0

    # Ensure index is accessible and sorted
    df = df.sort_index()

    for timestamp, row in df.iterrows():
        # Previous row values for MACD crossover
        # We use shifted columns to avoid iloc in loop for speed, but for simplicity here we keep it straightforward
        # We need the previous row's MACD. To make it safe, we check if we have history.
        
        # equity calculation
        current_close = float(row["close"])
        equity = balance + (position * current_close if position > 0 else 0.0)
        equity_curve.append({
            "time": int(timestamp.timestamp()),
            "value": round(equity, 2)
        })

    # Optimized loop using zip arrays for ~100x speedup over iterrows
    # Since we need to use it in API, fast is better
    timestamps = df.index.astype('int64') // 10**9 # UNIX seconds
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    ema20s = df[EMA20_COL].values
    ema50s = df[EMA50_COL].values
    rsis = df[RSI_COL].values
    macds = df[MACD_COL].values
    signals = df[SIGNAL_COL].values
    vol_smas = df[VOL_SMA_COL].values
    
    equity_curve.clear()
    
    for i in range(1, len(df)):
        ts = int(timestamps[i])
        close_p = float(closes[i])
        high_p = float(highs[i])
        low_p = float(lows[i])
        volume = float(volumes[i])
        
        ema20 = float(ema20s[i])
        ema50 = float(ema50s[i])
        rsi = float(rsis[i])
        macd = float(macds[i])
        signal = float(signals[i])
        vol_sma = float(vol_smas[i])
        
        prev_macd = float(macds[i-1])
        prev_signal = float(signals[i-1])

        # BUY Logic
        if position == 0:
            cond_trend = close_p > ema50 and ema20 > ema50
            cond_macd  = (prev_macd <= prev_signal) and (macd > signal)
            cond_rsi   = 40 < rsi < 65
            cond_body  = close_p > (high_p + low_p) / 2
            cond_vol   = vol_sma > 0 and volume > vol_sma * 1.05

            if cond_trend and cond_macd and cond_rsi and cond_body and cond_vol:
                spend         = balance * 0.98
                position      = spend / close_p
                balance      -= spend
                entry_price   = close_p
                highest_price = close_p
                trades_history.append({
                    "type": "BUY", 
                    "price": round(close_p, 4), 
                    "time": ts,
                    "reason": "golden_cross"
                })

        # SELL Logic
        elif position > 0:
            if high_p > highest_price:
                highest_price = high_p

            sell_price = None
            reason = ""

            # 1. Hard Stop-Loss
            if low_p <= entry_price * hard_stop:
                sell_price = entry_price * hard_stop
                reason     = "hard_stop"

            # 2. Fixed Take-Profit
            elif high_p >= entry_price * take_profit:
                sell_price = entry_price * take_profit
                reason     = "take_profit"

            # 3. Delayed Trailing Stop
            elif highest_price >= entry_price * trailing_activation:
                trigger = highest_price * trailing_distance
                if low_p <= trigger:
                    sell_price = trigger
                    reason     = "trailing_stop"

            if sell_price is not None:
                proceeds = position * sell_price
                balance += proceeds
                pnl_pct  = (sell_price - entry_price) / entry_price * 100
                trades_history.append({
                    "type":    "SELL",
                    "price":   round(sell_price, 4),
                    "time":    ts,
                    "pnl_pct": round(pnl_pct, 4),
                    "reason":  reason,
                })
                position      = 0.0
                entry_price   = 0.0
                highest_price = 0.0

        # Equity Tracking
        equity = balance + (position * close_p if position > 0 else 0.0)
        equity_curve.append({"time": ts, "value": round(equity, 2)})
        
        if equity > peak_balance:
            peak_balance = equity
        dd = (peak_balance - equity) / peak_balance * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # Close left-over position at the end
    if position > 0:
        lc = float(closes[-1])
        ts = int(timestamps[-1])
        balance += position * lc
        trades_history.append({
            "type": "SELL", "price": round(lc, 4), "time": ts,
            "pnl_pct": round((lc - entry_price) / entry_price * 100, 4),
            "reason": "end_of_data",
        })
        equity = balance
        equity_curve.append({"time": ts, "value": round(equity, 2)})

    sells  = [t for t in trades_history if t["type"] == "SELL"]
    wins   = [t for t in sells if t.get("pnl_pct", 0) > 0]
    losses = [t for t in sells if t.get("pnl_pct", 0) <= 0]

    avg_win  = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0

    metrics = {
        "final_balance":  round(balance, 2),
        "total_return_pct": round((balance - initial_balance) / initial_balance * 100, 2),
        "total_trades":   len(sells),
        "win_rate_pct":   round(len(wins) / len(sells) * 100, 2) if sells else 0.0,
        "avg_win_pct":    round(avg_win,  2),
        "avg_loss_pct":   round(avg_loss, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
    }

    # Format chart lines
    # candlestick data
    chart_candles = []
    # sampling the candles to limit payload if it's too big, but lightweight-charts handles 5K-10K points easily
    for i in range(1, len(df)):
        chart_candles.append({
            "time": int(timestamps[i]),
            "open": float(df["open"].iloc[i]),
            "high": float(df["high"].iloc[i]),
            "low": float(df["low"].iloc[i]),
            "close": float(df["close"].iloc[i])
        })
        
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades_history,
        "candles": chart_candles
    }
