"""
Phase 26 – Hyperparameter Grid Search
=======================================
Downloads 3 years of 1h BTC/USDT once, then runs the Golden Strategy
simulation across a grid of (trailing_activation × take_profit) parameters
to find the most profitable configuration.

Fixed parameters:
  hard_stop          = 0.97   (3% hard stop)
  trailing_distance  = 0.985  (1.5% trail below peak)

Search grid:
  trailing_activation : [1.03, 1.04, 1.05]  (activate trail after +3/4/5%)
  take_profit         : [1.08, 1.10, 1.15]  (fixed TP at +8/10/15%)
"""

import asyncio
import itertools
import sys
import time
from datetime import datetime, timezone, timedelta

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Data Fetch (unchanged – paginated, same as Phase 25)
# ---------------------------------------------------------------------------

async def fetch_historical_data(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    since_ms: int | None = None,
    batch_size: int = 1000,
) -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        all_ohlcv: list[list] = []
        fetch_since = since_ms
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        print(f"\n[DATA] Paginated download: {symbol} | {timeframe}")
        print(f"[DATA] From {datetime.fromtimestamp(since_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')}"
              f" → {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n")

        page = 0
        t0 = time.time()

        while True:
            page += 1
            candles = await exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=fetch_since, limit=batch_size
            )
            if not candles:
                break
            all_ohlcv.extend(candles)
            last_ts = candles[-1][0]
            last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"  Page {page:>3} | {len(all_ohlcv):>6} candles | Latest: {last_dt} | {time.time()-t0:.1f}s")
            if len(candles) < batch_size or last_ts >= now_ms:
                break
            fetch_since = last_ts + 1
            await asyncio.sleep(0.1)

        print(f"\n[DATA] Complete: {len(all_ohlcv)} candles in {time.time()-t0:.1f}s")

        df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.drop_duplicates(subset="timestamp", inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        print("[DATA] Calculating indicators...")
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()
        df.dropna(inplace=True)
        df.reset_index(inplace=True)
        print(f"[DATA] Clean dataset: {len(df)} candles\n")
        return df
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# Task 2 – Parameterised run_backtest
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, params: dict, initial_balance: float = 100.0) -> dict:
    """
    Simulates the Golden Strategy with the given exit parameters.

    params keys:
      hard_stop           (float) e.g. 0.97
      trailing_activation (float) e.g. 1.03  → activate trail after +3%
      trailing_distance   (float) e.g. 0.985 → trail 1.5% below peak
      take_profit         (float) e.g. 1.08  → fixed TP at +8%
    """
    hard_stop           = params["hard_stop"]
    trailing_activation = params["trailing_activation"]
    trailing_distance   = params["trailing_distance"]
    take_profit         = params["take_profit"]

    balance       : float = initial_balance
    position      : float = 0.0
    entry_price   : float = 0.0
    highest_price : float = 0.0
    trades_history: list[dict] = []

    MACD_COL    = "MACD_12_26_9"
    SIGNAL_COL  = "MACDs_12_26_9"
    EMA20_COL   = "EMA_20"
    EMA50_COL   = "EMA_50"
    RSI_COL     = "RSI_14"
    VOL_SMA_COL = "VOL_SMA_20"

    peak_balance : float = initial_balance
    max_drawdown : float = 0.0

    for i in range(1, len(df)):
        row      = df.iloc[i]
        prev_row = df.iloc[i - 1]

        close       = row["close"]
        high        = row["high"]
        low         = row["low"]
        volume      = row["volume"]
        ema20       = row[EMA20_COL]
        ema50       = row[EMA50_COL]
        rsi         = row[RSI_COL]
        macd        = row[MACD_COL]
        signal      = row[SIGNAL_COL]
        vol_sma     = row[VOL_SMA_COL]
        prev_macd   = prev_row[MACD_COL]
        prev_signal = prev_row[SIGNAL_COL]

        # ── BUY (all 5 Golden filters) ────────────────────────────────────
        if position == 0:
            cond_trend = close > ema50 and ema20 > ema50
            cond_macd  = (prev_macd <= prev_signal) and (macd > signal)
            cond_rsi   = 40 < rsi < 65
            cond_body  = close > (high + low) / 2
            cond_vol   = vol_sma > 0 and volume > vol_sma * 1.05

            if cond_trend and cond_macd and cond_rsi and cond_body and cond_vol:
                spend         = balance * 0.98
                position      = spend / close
                balance      -= spend
                entry_price   = close
                highest_price = close
                trades_history.append({"type": "BUY", "price": close})

        # ── SELL (3-priority exit logic) ──────────────────────────────────
        elif position > 0:
            if high > highest_price:
                highest_price = high

            sell_price: float | None = None
            reason: str = ""

            # 1. Hard Stop-Loss
            if low <= entry_price * hard_stop:
                sell_price = entry_price * hard_stop
                reason     = "hard_stop"

            # 2. Fixed Take-Profit
            elif high >= entry_price * take_profit:
                sell_price = entry_price * take_profit
                reason     = "take_profit"

            # 3. Delayed Trailing Stop
            elif highest_price >= entry_price * trailing_activation:
                trigger = highest_price * trailing_distance
                if low <= trigger:
                    sell_price = trigger
                    reason     = "trailing_stop"

            if sell_price is not None:
                proceeds = position * sell_price
                balance += proceeds
                pnl_pct  = (sell_price - entry_price) / entry_price * 100
                trades_history.append({
                    "type":    "SELL",
                    "price":   sell_price,
                    "pnl_pct": round(pnl_pct, 4),
                    "reason":  reason,
                })
                position      = 0.0
                entry_price   = 0.0
                highest_price = 0.0

        # Drawdown tracking
        equity = balance + (position * close if position > 0 else 0.0)
        if equity > peak_balance:
            peak_balance = equity
        dd = (peak_balance - equity) / peak_balance * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # Force-close remaining position
    if position > 0:
        lc = df.iloc[-1]["close"]
        balance += position * lc
        trades_history.append({
            "type": "SELL", "price": lc,
            "pnl_pct": round((lc - entry_price) / entry_price * 100, 4),
            "reason": "end_of_data",
        })

    sells  = [t for t in trades_history if t["type"] == "SELL"]
    wins   = [t for t in sells if t.get("pnl_pct", 0) > 0]
    losses = [t for t in sells if t.get("pnl_pct", 0) <= 0]

    avg_win  = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0

    return {
        "params":         params,
        "final_balance":  balance,
        "total_return":   round((balance - initial_balance) / initial_balance * 100, 2),
        "total_trades":   len(sells),
        "win_rate":       round(len(wins) / len(sells) * 100, 2) if sells else 0.0,
        "avg_win":        round(avg_win,  4),
        "avg_loss":       round(avg_loss, 4),
        "max_drawdown":   round(max_drawdown, 2),
        "expectancy":     round((len(wins) / len(sells)) * avg_win +
                                (len(losses) / len(sells)) * avg_loss, 4) if sells else 0.0,
    }


# ---------------------------------------------------------------------------
# Task 3 – Grid Search Report
# ---------------------------------------------------------------------------

def run_grid_search(df: pd.DataFrame, initial_balance: float = 100.0) -> list[dict]:
    """Tests all parameter combinations and returns results sorted by total return."""
    # Search space
    trailing_activations = [1.03, 1.04, 1.05]
    take_profits         = [1.08, 1.10, 1.15]
    HARD_STOP            = 0.97
    TRAILING_DISTANCE    = 0.985

    grid = list(itertools.product(trailing_activations, take_profits))
    total = len(grid)          # 9 combinations
    results: list[dict] = []

    print(f"[GRID] Running {total} parameter combinations...\n")

    for idx, (trail_act, tp) in enumerate(grid, 1):
        params = {
            "hard_stop":           HARD_STOP,
            "trailing_activation": trail_act,
            "trailing_distance":   TRAILING_DISTANCE,
            "take_profit":         tp,
        }
        label = (f"  Trail-Act={trail_act:.0%}  TP={tp:.0%}  "
                 f"Stop={HARD_STOP:.0%}  Trail-Dist={TRAILING_DISTANCE:.1%}")
        print(f"[{idx:>2}/{total}] Testing {label} ...", end=" ", flush=True)

        t0  = time.time()
        res = run_backtest(df, params, initial_balance)
        print(f"Return={res['total_return']:+.2f}%  WR={res['win_rate']:.1f}%  "
              f"Trades={res['total_trades']}  ({time.time()-t0:.2f}s)")
        results.append(res)

    # Sort best → worst by total return
    results.sort(key=lambda r: r["total_return"], reverse=True)
    return results


def print_grid_report(results: list[dict]) -> None:
    """Prints an ASCII table of the top 5 parameter combinations."""
    top_n = results[:5]
    sep = "-" * 96

    print(f"\n\n{'='*96}")
    print(f"{'GRID SEARCH RESULTS  —  TOP 5 PARAMETER COMBINATIONS':^96}")
    print(f"{'BTC/USDT | 1h | 3-Year Dataset':^96}")
    print(f"{'='*96}")
    print(f"\n  {'Rank':<5} {'Trail-Act':>10} {'Take-Profit':>12} {'Return':>9} "
          f"{'Win Rate':>9} {'Trades':>7} {'Avg Win':>9} {'Avg Loss':>9} "
          f"{'Expect':>8} {'Max DD':>8}")
    print(f"  {sep}")

    for rank, r in enumerate(top_n, 1):
        p   = r["params"]
        tp_pct   = (p["take_profit"]         - 1) * 100
        ta_pct   = (p["trailing_activation"] - 1) * 100
        ret_str  = f"{r['total_return']:+.2f}%"
        wr_str   = f"{r['win_rate']:.1f}%"
        aw_str   = f"{r['avg_win']:+.2f}%"
        al_str   = f"{r['avg_loss']:+.2f}%"
        ex_str   = f"{r['expectancy']:+.3f}%"
        dd_str   = f"{r['max_drawdown']:.2f}%"

        marker = " <-- BEST" if rank == 1 else ""
        print(f"  #{rank:<4} {f'+{ta_pct:.0f}%':>10} {f'+{tp_pct:.0f}%':>12} "
              f"{ret_str:>9} {wr_str:>9} {r['total_trades']:>7} "
              f"{aw_str:>9} {al_str:>9} {ex_str:>8} {dd_str:>8}{marker}")

    print(f"  {sep}\n")

    # Detailed breakdown of the #1 combo
    best = results[0]
    bp   = best["params"]
    print(f"  WINNER DETAILS:")
    print(f"    Hard Stop         : {(1-bp['hard_stop'])*100:.1f}% loss")
    print(f"    Trailing Activates: after +{(bp['trailing_activation']-1)*100:.1f}% profit")
    print(f"    Trailing Distance : {(1-bp['trailing_distance'])*100:.1f}% below peak")
    print(f"    Take Profit       : +{(bp['take_profit']-1)*100:.1f}%")
    print(f"    Total Return      : {best['total_return']:+.2f}%")
    print(f"    Win Rate          : {best['win_rate']:.2f}%")
    print(f"    Expectancy/trade  : {best['expectancy']:+.3f}%")
    print(f"    Max Drawdown      : {best['max_drawdown']}%")
    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main() -> None:
    SYMBOL          = "BTC/USDT"
    TIMEFRAME       = "1h"
    DAYS_BACK       = 3 * 365
    INITIAL_BALANCE = 100.0

    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).timestamp() * 1000
    )

    print("=" * 64)
    print("  Phase 26 – Hyperparameter Grid Search")
    print(f"  {SYMBOL} | {TIMEFRAME} | Last {DAYS_BACK} days (3 years)")
    print("=" * 64)

    # Download dataset ONCE, reuse for all 9 simulations
    df = await fetch_historical_data(
        symbol=SYMBOL, timeframe=TIMEFRAME,
        since_ms=since_ms, batch_size=1000,
    )

    results = run_grid_search(df, initial_balance=INITIAL_BALANCE)
    print_grid_report(results)


if __name__ == "__main__":
    asyncio.run(main())
