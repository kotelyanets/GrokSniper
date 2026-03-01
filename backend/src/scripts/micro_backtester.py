"""
Phase 32.5 – Heavyweight Micro-Backtester (1-minute × 3 Years)
================================================================
Downloads ~1.57 million 1m BTC/USDT candles, caches to Parquet,
and runs the Golden Strategy simulation with exchange trading fees
(0.1% taker fee per side = 0.2% round-trip).
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Directory to store cache files
CACHE_DIR = Path(__file__).resolve().parent

# Exchange fee per side (Binance taker fee = 0.1%)
FEE_PER_SIDE = 0.001
ROUND_TRIP_FEE = FEE_PER_SIDE * 2  # 0.2%


# ---------------------------------------------------------------------------
# Task 1 – Massive Data Fetcher & Cacher
# ---------------------------------------------------------------------------

async def get_cached_or_fetch_1m_data(
    ticker: str = "BTC/USDT",
    days: int = 1095,
) -> pd.DataFrame:
    """
    Returns a DataFrame of 1m candles with TA indicators.
    Loads from a Parquet cache if available, otherwise fetches from Binance.
    """
    ticker_safe = ticker.replace("/", "_").replace(":", "_")
    cache_file = CACHE_DIR / f"cache_{ticker_safe}_1m_3y.parquet"

    # ── Cache check ────────────────────────────────────────────────────────
    if cache_file.exists():
        print(f"[CACHE] Loading cached data from {cache_file.name} ...")
        t0 = time.time()
        df = pd.read_parquet(cache_file)
        print(f"[CACHE] Loaded {len(df):,} candles in {time.time()-t0:.1f}s")
        return df

    # ── Fetch from Binance ─────────────────────────────────────────────────
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )

        print(f"\n{'='*70}")
        print(f"  MASSIVE DATA DOWNLOAD: {ticker} | 1m | {days} days")
        print(f"  From {datetime.fromtimestamp(since_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')}"
              f" → {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
        print(f"  Expected: ~{days * 24 * 60:,} candles")
        print(f"{'='*70}\n")

        all_ohlcv: list[list] = []
        fetch_since = since_ms
        page = 0
        t0 = time.time()

        while True:
            page += 1
            candles = await exchange.fetch_ohlcv(
                ticker, timeframe="1m", since=fetch_since, limit=1000
            )
            if not candles:
                break

            all_ohlcv.extend(candles)
            last_ts = candles[-1][0]
            last_dt = datetime.fromtimestamp(
                last_ts / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M")

            # Progress every 50 pages to avoid flooding console
            if page % 50 == 0 or page == 1:
                elapsed = time.time() - t0
                rate = len(all_ohlcv) / elapsed if elapsed > 0 else 0
                eta_mins = ((days * 24 * 60) - len(all_ohlcv)) / rate / 60 if rate > 0 else 0
                print(
                    f"  Page {page:>5} | {len(all_ohlcv):>10,} candles | "
                    f"Latest: {last_dt} | {elapsed:.0f}s elapsed | "
                    f"ETA: ~{eta_mins:.0f} min"
                )

            if len(candles) < 1000 or last_ts >= now_ms:
                break

            fetch_since = last_ts + 1
            await asyncio.sleep(0.1)  # Rate limiting to avoid IP bans

        elapsed = time.time() - t0
        print(f"\n[DATA] Download complete: {len(all_ohlcv):,} candles in {elapsed:.1f}s")

        # Build DataFrame
        df = pd.DataFrame(
            all_ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df.drop_duplicates(subset="timestamp", inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # ── TA indicators ──────────────────────────────────────────────────
        print("[DATA] Calculating TA indicators on 1m data (this may take a moment)...")
        t1 = time.time()
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()
        df.dropna(inplace=True)
        df.reset_index(inplace=True)
        print(f"[DATA] Indicators calculated in {time.time()-t1:.1f}s | "
              f"Clean dataset: {len(df):,} candles")

        # ── Save to Parquet cache ──────────────────────────────────────────
        print(f"[CACHE] Saving to {cache_file.name} ...")
        df.to_parquet(cache_file, index=False)
        print(f"[CACHE] Saved ({cache_file.stat().st_size / (1024*1024):.1f} MB)")

        return df
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# Task 2 – Fee-Adjusted Backtest Simulation
# ---------------------------------------------------------------------------

def run_backtest_1m(
    df: pd.DataFrame,
    params: dict,
    initial_balance: float = 100.0,
) -> dict:
    """
    Runs the Golden Strategy on 1m candles with exchange fee deductions.

    Every trade round-trip costs 0.2% (0.1% entry + 0.1% exit taker fee).

    params keys:
      hard_stop           (float) e.g. 0.97
      trailing_activation (float) e.g. 1.05
      trailing_distance   (float) e.g. 0.985
      take_profit         (float) e.g. 1.10
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

    total_fees_paid: float = 0.0
    total_rows = len(df)

    print(f"\n[SIM] Starting 1m simulation on {total_rows:,} candles...")
    t0 = time.time()

    for i in range(1, total_rows):
        row      = df.iloc[i]
        prev_row = df.iloc[i - 1]

        close   = row["close"]
        high    = row["high"]
        low     = row["low"]
        volume  = row["volume"]
        ema20   = row[EMA20_COL]
        ema50   = row[EMA50_COL]
        rsi     = row[RSI_COL]
        macd    = row[MACD_COL]
        signal  = row[SIGNAL_COL]
        vol_sma = row[VOL_SMA_COL]
        prev_macd   = prev_row[MACD_COL]
        prev_signal = prev_row[SIGNAL_COL]

        # Progress logging every 250k candles
        if i % 250_000 == 0:
            pct = i / total_rows * 100
            print(f"  [SIM] {pct:.0f}% ({i:,}/{total_rows:,}) | "
                  f"Balance: ${balance:.2f} | Trades: {len(trades_history)//2}")

        # ── BUY (all 5 Golden filters) ────────────────────────────────────
        if position == 0:
            cond_trend = close > ema50 and ema20 > ema50
            cond_macd  = (prev_macd <= prev_signal) and (macd > signal)
            cond_rsi   = 40 < rsi < 65
            cond_body  = close > (high + low) / 2
            cond_vol   = vol_sma > 0 and volume > vol_sma * 1.05

            if cond_trend and cond_macd and cond_rsi and cond_body and cond_vol:
                spend = balance * 0.98
                # Apply entry fee: we lose 0.1% on the buy
                effective_spend = spend * (1 - FEE_PER_SIDE)
                entry_fee = spend * FEE_PER_SIDE
                total_fees_paid += entry_fee

                position      = effective_spend / close
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
                # Apply exit fee: we lose 0.1% on the sell
                gross_proceeds = position * sell_price
                exit_fee = gross_proceeds * FEE_PER_SIDE
                net_proceeds = gross_proceeds * (1 - FEE_PER_SIDE)
                total_fees_paid += exit_fee

                balance += net_proceeds

                # Net PnL after both fees
                gross_pnl_pct = (sell_price - entry_price) / entry_price * 100
                net_pnl_pct = gross_pnl_pct - (ROUND_TRIP_FEE * 100)

                trades_history.append({
                    "type":        "SELL",
                    "price":       sell_price,
                    "gross_pnl":   round(gross_pnl_pct, 4),
                    "net_pnl":     round(net_pnl_pct, 4),
                    "reason":      reason,
                    "fee_paid":    round(entry_fee + exit_fee, 6) if 'entry_fee' in dir() else round(exit_fee, 6),
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
        gross_proceeds = position * lc
        net_proceeds = gross_proceeds * (1 - FEE_PER_SIDE)
        exit_fee = gross_proceeds * FEE_PER_SIDE
        total_fees_paid += exit_fee
        balance += net_proceeds

        gross_pnl_pct = (lc - entry_price) / entry_price * 100
        net_pnl_pct = gross_pnl_pct - (ROUND_TRIP_FEE * 100)
        trades_history.append({
            "type":      "SELL",
            "price":     lc,
            "gross_pnl": round(gross_pnl_pct, 4),
            "net_pnl":   round(net_pnl_pct, 4),
            "reason":    "end_of_data",
        })

    elapsed = time.time() - t0
    print(f"[SIM] Complete in {elapsed:.1f}s")

    # ── Compute statistics ─────────────────────────────────────────────────
    sells  = [t for t in trades_history if t["type"] == "SELL"]
    wins   = [t for t in sells if t.get("net_pnl", 0) > 0]
    losses = [t for t in sells if t.get("net_pnl", 0) <= 0]

    avg_win  = sum(t["net_pnl"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0.0

    return {
        "final_balance":   balance,
        "total_return":    round((balance - initial_balance) / initial_balance * 100, 2),
        "total_trades":    len(sells),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / len(sells) * 100, 2) if sells else 0.0,
        "avg_win_net":     round(avg_win,  4),
        "avg_loss_net":    round(avg_loss, 4),
        "max_drawdown":    round(max_drawdown, 2),
        "total_fees_paid": round(total_fees_paid, 4),
        "expectancy":      round(
            (len(wins) / len(sells)) * avg_win +
            (len(losses) / len(sells)) * avg_loss, 4
        ) if sells else 0.0,
        "exit_reasons":    {
            "hard_stop":     len([t for t in sells if t["reason"] == "hard_stop"]),
            "take_profit":   len([t for t in sells if t["reason"] == "take_profit"]),
            "trailing_stop": len([t for t in sells if t["reason"] == "trailing_stop"]),
            "end_of_data":   len([t for t in sells if t["reason"] == "end_of_data"]),
        },
    }


# ---------------------------------------------------------------------------
# Task 3 – Report Printing & Execution
# ---------------------------------------------------------------------------

def print_report(result: dict, ticker: str, params: dict) -> None:
    """Prints a formatted summary of the backtest results."""
    sep = "=" * 70

    print(f"\n\n{sep}")
    print(f"{'MICRO-BACKTESTER RESULTS  —  1m × 3 YEARS':^70}")
    print(f"{f'{ticker} | After 0.2% Round-Trip Fees':^70}")
    print(f"{sep}\n")

    print(f"  STRATEGY PARAMETERS:")
    print(f"    Hard Stop           : {(1-params['hard_stop'])*100:.1f}% loss")
    print(f"    Trailing Activates  : after +{(params['trailing_activation']-1)*100:.1f}% profit")
    print(f"    Trailing Distance   : {(1-params['trailing_distance'])*100:.1f}% below peak")
    print(f"    Take Profit         : +{(params['take_profit']-1)*100:.1f}%")
    print()

    print(f"  PERFORMANCE:")
    print(f"    Total Trades        : {result['total_trades']}")
    print(f"    Wins / Losses       : {result['wins']} / {result['losses']}")
    print(f"    Win Rate            : {result['win_rate']:.2f}%")
    print(f"    Avg Win  (net)      : {result['avg_win_net']:+.4f}%")
    print(f"    Avg Loss (net)      : {result['avg_loss_net']:+.4f}%")
    print(f"    Expectancy/trade    : {result['expectancy']:+.4f}%")
    print()

    print(f"  RETURNS:")
    print(f"    Initial Balance     : $100.00")
    print(f"    Final Balance       : ${result['final_balance']:.2f}")
    print(f"    Total Net Return    : {result['total_return']:+.2f}%")
    print(f"    Total Fees Paid     : ${result['total_fees_paid']:.4f}")
    print(f"    Max Drawdown        : {result['max_drawdown']:.2f}%")
    print()

    er = result["exit_reasons"]
    print(f"  EXIT BREAKDOWN:")
    print(f"    Hard Stop           : {er['hard_stop']}")
    print(f"    Take Profit         : {er['take_profit']}")
    print(f"    Trailing Stop       : {er['trailing_stop']}")
    print(f"    End of Data         : {er['end_of_data']}")
    print(f"\n{sep}\n")


async def main() -> None:
    TICKER          = "BTC/USDT"
    DAYS            = 1095  # 3 years
    INITIAL_BALANCE = 100.0

    # Best params from Phase 26 grid search
    PARAMS = {
        "hard_stop":           0.97,
        "trailing_activation": 1.05,
        "trailing_distance":   0.985,
        "take_profit":         1.10,
    }

    print("=" * 70)
    print("  Phase 32.5 – Heavyweight Micro-Backtester")
    print(f"  {TICKER} | 1m | Last {DAYS} days (3 years)")
    print(f"  Fees: {FEE_PER_SIDE*100:.1f}% per side ({ROUND_TRIP_FEE*100:.1f}% round-trip)")
    print("=" * 70)

    # Step 1: Get data (cached or fresh download)
    df = await get_cached_or_fetch_1m_data(ticker=TICKER, days=DAYS)

    # Step 2: Run fee-adjusted simulation
    result = run_backtest_1m(df, params=PARAMS, initial_balance=INITIAL_BALANCE)

    # Step 3: Print report
    print_report(result, ticker=TICKER, params=PARAMS)


if __name__ == "__main__":
    asyncio.run(main())
