"""
Phase 43.1 — Comprehensive Stress Test Optimization
===================================================
Backtests the EXACT live GrokSniper Hyper-Trend strategy across
multiple tickers on 3 years of 4h candles with realistic Binance taker fees (0.2% round-trip).

Optimizations in Phase 43.1:
  - Timeframe: 4h (reduces noise and overtrading)
  - LONG  exit  : ATR dynamic SL OR delayed trailing (activates at +4%, trails by 2.5%)
  - SHORT exit  : ATR dynamic SL OR delayed trailing (activates at +4%, trails by 2.5%)
  - BTC Health Guard:
      - LONG only if BTC > BTC 4h 200 EMA
      - SHORT only if BTC < BTC 4h 200 EMA

Run:
  cd c:\\Users\\andko\\Desktop\\sniper_bot
  python -m backend.src.scripts.stress_test
"""

import asyncio
import sys
import time
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
import pandas_ta as ta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TICKERS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
TIMEFRAME = "4h"
DAYS_BACK = 3 * 365
INITIAL_BALANCE = 10_000.0
POSITION_FRACTION = 0.98   # use 98% of balance per trade
FEE_PER_SIDE = 0.001       # 0.1% taker fee (0.2% round-trip)

# Phase 44.3 Optuna parameters
RSI_LOWER = 38
RSI_UPPER = 65
ATR_MULTIPLIER = 1.9

# Risk params
TRAILING_ACTIVATION_PCT = 0.054  # 5.4% profit triggers trailing stop
TRAILING_PULLBACK_PCT = 0.003    # 0.3% pullback closes trade
VOL_SMA_MULTIPLIER = 1.02        # volume must be > 1.02x 20-candle SMA
MIN_CANDLE_BODY_PCT = 0.03       # candle body must be > 3% of total wick-to-wick range

CACHE_DIR = Path(__file__).resolve().parent / "cache_stress_test"
OUTPUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1. Data Fetcher — paginated download with local pickle cache
# ---------------------------------------------------------------------------

async def fetch_ticker_data(
    symbol: str,
    timeframe: str = "4h",
    days: int = 1095,
) -> pd.DataFrame:
    """Downloads 4h candles from Binance. Returns cached DataFrame if exists."""
    CACHE_DIR.mkdir(exist_ok=True)
    safe_name = symbol.replace("/", "_")
    cache_file = CACHE_DIR / f"{safe_name}_{timeframe}_{days}d_v2.pkl"

    if cache_file.exists():
        print(f"  [CACHE] Loading {cache_file.name} ...")
        df = pd.read_pickle(cache_file)
        print(f"  [CACHE] {len(df):,} candles loaded")
        return df

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        print(f"  [DOWNLOAD] {symbol} | {timeframe} | {days} days ...")

        all_ohlcv: list[list] = []
        fetch_since = since_ms
        page = 0
        t0 = time.time()

        while True:
            page += 1
            candles = await exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=fetch_since, limit=1000
            )
            if not candles:
                break
            all_ohlcv.extend(candles)
            last_ts = candles[-1][0]

            if page % 10 == 0 or page == 1:
                last_dt = datetime.fromtimestamp(
                    last_ts / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
                print(
                    f"    Page {page:>4} | {len(all_ohlcv):>7,} candles | "
                    f"Latest: {last_dt} | {time.time()-t0:.0f}s"
                )

            if len(candles) < 1000 or last_ts >= now_ms:
                break
            fetch_since = last_ts + 1
            await asyncio.sleep(0.12)

        elapsed = time.time() - t0
        print(f"  [DOWNLOAD] {len(all_ohlcv):,} candles in {elapsed:.0f}s")

        df = pd.DataFrame(
            all_ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df.drop_duplicates(subset="timestamp", inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # TA indicators
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)  # Added for BTC Health Guard
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.atr(length=14, append=True)
        df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()
        df.dropna(inplace=True)
        df.reset_index(inplace=True)

        df.to_pickle(cache_file)
        print(f"  [CACHE] Saved to {cache_file.name}")
        return df
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# 2. Backtest Engine
# ---------------------------------------------------------------------------

def run_stress_test(
    df: pd.DataFrame,
    symbol: str,
    initial_balance: float = 10_000.0,
) -> dict:
    """
    Simulates the optimized live strategy on 4h candles.
    Returns a dict with all metrics, trade list, and equity curve.
    """
    balance = initial_balance
    qty = 0.0              # position size in asset units
    entry_price = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    notional = 0.0         # capital deployed (after entry fee)
    side = ""              # "LONG" or "SHORT" or ""
    dynamic_sl = 0.0
    entry_ts = None
    entry_spend = 0.0      # raw amount deducted from balance

    trades: list[dict] = []
    equity_curve: list[dict] = []
    peak_equity = initial_balance
    max_drawdown = 0.0

    EMA20 = "EMA_20"
    EMA50 = "EMA_50"
    RSI = "RSI_14"
    MACD_L = "MACD_12_26_9"
    MACD_S = "MACDs_12_26_9"
    VOL_SMA = "VOL_SMA_20"
    ATR = "ATRr_14"

    total_rows = len(df)
    t0 = time.time()

    for i in range(1, total_rows):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        close = row["close"]
        high = row["high"]
        low = row["low"]
        volume = row["volume"]
        ema20 = row[EMA20]
        ema50 = row[EMA50]
        rsi = row[RSI]
        macd = row[MACD_L]
        signal = row[MACD_S]
        vol_sma = row[VOL_SMA]
        atr = row[ATR]
        prev_macd = prev[MACD_L]
        prev_signal = prev[MACD_S]
        ts = row["timestamp"]
        
        btc_close = row["BTC_close"]
        btc_ema_200 = row["BTC_EMA_200"]

        # Progress
        if i % 5000 == 0:
            pct = i / total_rows * 100
            sys.stdout.write(
                f"\r  [{symbol}] {pct:5.1f}% | ${balance:,.2f} | "
                f"Trades: {len([t for t in trades if t['action'] == 'EXIT'])}"
            )
            sys.stdout.flush()

        # ══════════════════════════════════════════════════════════════════
        # NO POSITION — check for entries
        # ══════════════════════════════════════════════════════════════════
        if qty == 0:
            entered = False

            # ── LONG ENTRY ────────────────────────────────────────────────
            cond_btc_health = btc_close > btc_ema_200
            
            cond_trend = close > ema50 and ema20 > ema50
            cond_macd = (prev_macd <= prev_signal) and (macd > signal)
            cond_rsi = RSI_LOWER < rsi < RSI_UPPER
            candle_mid = (high + low) / 2
            cond_body = (close - candle_mid) / (high - low + 1e-9) > MIN_CANDLE_BODY_PCT
            cond_vol = vol_sma > 0 and volume > vol_sma * VOL_SMA_MULTIPLIER

            if cond_btc_health and cond_trend and cond_macd and cond_rsi and cond_body and cond_vol:
                spend = balance * POSITION_FRACTION
                entry_fee = spend * FEE_PER_SIDE
                notional = spend - entry_fee
                qty = notional / close
                balance -= spend
                entry_price = close
                highest_price = close
                lowest_price = close
                side = "LONG"
                atr_dist = atr * ATR_MULTIPLIER if atr > 0 else close * 0.03
                dynamic_sl = close - atr_dist
                entry_ts = ts
                entry_spend = spend
                entered = True

                trades.append({
                    "symbol": symbol, "side": "LONG", "action": "ENTRY",
                    "timestamp": str(ts), "price": close, "size_usdt": round(spend, 2),
                    "fee": round(entry_fee, 4), "balance_after": round(balance, 2),
                    "atr": round(atr, 4), "dynamic_sl": round(dynamic_sl, 4),
                })

            # ── SHORT ENTRY ───────────────────────────────────────────────
            if not entered:
                cond_btc_health_short = btc_close < btc_ema_200
                
                cond_bear_trend = close < ema50 and ema20 < ema50
                cond_bear_macd = (prev_macd >= prev_signal) and (macd < signal)
                cond_bear_rsi = (100 - RSI_UPPER) < rsi < (100 - RSI_LOWER)
                
                # Assuming cond_body and cond_vol are also applied to short entries
                candle_mid_short = (high + low) / 2
                cond_bear_body = (candle_mid_short - close) / (high - low + 1e-9) > MIN_CANDLE_BODY_PCT
                cond_bear_vol = vol_sma > 0 and volume > vol_sma * VOL_SMA_MULTIPLIER

                if cond_btc_health_short and cond_bear_trend and cond_bear_macd and cond_bear_rsi and cond_bear_body and cond_bear_vol:
                    spend = balance * POSITION_FRACTION
                    entry_fee = spend * FEE_PER_SIDE
                    notional = spend - entry_fee
                    qty = notional / close
                    balance -= spend
                    entry_price = close
                    highest_price = close
                    lowest_price = close
                    side = "SHORT"
                    atr_dist = atr * 1.5 if atr > 0 else close * 0.03
                    dynamic_sl = close + atr_dist
                    entry_ts = ts
                    entry_spend = spend
                    entered = True

                    trades.append({
                        "symbol": symbol, "side": "SHORT", "action": "ENTRY",
                        "timestamp": str(ts), "price": close, "size_usdt": round(spend, 2),
                        "fee": round(entry_fee, 4), "balance_after": round(balance, 2),
                        "atr": round(atr, 4), "dynamic_sl": round(dynamic_sl, 4),
                    })

        # ══════════════════════════════════════════════════════════════════
        # HOLDING LONG — check for exits
        # ══════════════════════════════════════════════════════════════════
        elif side == "LONG":
            if high > highest_price:
                highest_price = high

            exit_price = None
            exit_reason = ""

            # 1. Hard Stop-Loss (ATR dynamic)
            if low <= dynamic_sl:
                exit_price = dynamic_sl
                exit_reason = "hard_stop"

            # 2. Delayed Trailing: activates after +4%, trails 2.5% below peak
            elif highest_price >= entry_price * 1.04:
                trailing_trigger = highest_price * (1.0 - TRAILING_PULLBACK_PCT)
                if low <= trailing_trigger:
                    exit_price = trailing_trigger
                    exit_reason = "trailing_stop"

            if exit_price is not None:
                gross = qty * exit_price
                exit_fee = gross * FEE_PER_SIDE
                balance += gross - exit_fee

                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                pnl_usd = (gross - exit_fee) - notional

                trades.append({
                    "symbol": symbol, "side": "LONG", "action": "EXIT",
                    "timestamp": str(ts), "price": round(exit_price, 6),
                    "entry_price": round(entry_price, 6),
                    "pnl_pct": round(pnl_pct, 4), "pnl_usd": round(pnl_usd, 2),
                    "fee": round(exit_fee, 4), "reason": exit_reason,
                    "peak_price": round(highest_price, 6),
                    "balance_after": round(balance, 2),
                })
                qty = 0.0; side = ""; entry_price = 0.0; notional = 0.0

        # ══════════════════════════════════════════════════════════════════
        # HOLDING SHORT — check for exits
        # ══════════════════════════════════════════════════════════════════
        elif side == "SHORT":
            if low < lowest_price:
                lowest_price = low

            exit_price = None
            exit_reason = ""

            # 1. Hard Stop-Loss (ATR dynamic — SHORT: price goes UP)
            if high >= dynamic_sl:
                exit_price = dynamic_sl
                exit_reason = "hard_stop"

            # 2. Delayed Trailing: activates after -4% (price drops 4%), trails 2.5% above trough
            elif lowest_price <= entry_price * 0.96:
                trailing_trigger = lowest_price * (1.0 + TRAILING_PULLBACK_PCT)
                if high >= trailing_trigger:
                    exit_price = trailing_trigger
                    exit_reason = "trailing_stop"

            if exit_price is not None:
                gross = qty * (2 * entry_price - exit_price)
                if gross < 0:
                    gross = 0.0   # capped at total loss
                exit_fee = gross * FEE_PER_SIDE
                balance += gross - exit_fee

                pnl_pct = ((entry_price - exit_price) / entry_price) * 100
                pnl_usd = (gross - exit_fee) - notional

                trades.append({
                    "symbol": symbol, "side": "SHORT", "action": "EXIT",
                    "timestamp": str(ts), "price": round(exit_price, 6),
                    "entry_price": round(entry_price, 6),
                    "pnl_pct": round(pnl_pct, 4), "pnl_usd": round(pnl_usd, 2),
                    "fee": round(exit_fee, 4), "reason": exit_reason,
                    "trough_price": round(lowest_price, 6),
                    "balance_after": round(balance, 2),
                })
                qty = 0.0; side = ""; entry_price = 0.0; notional = 0.0

        # ── Equity (mark-to-market) ──────────────────────────────────────
        if qty > 0 and side == "LONG":
            equity = balance + qty * close
        elif qty > 0 and side == "SHORT":
            equity = balance + qty * (2 * entry_price - close)
        else:
            equity = balance

        # Subsample equity curve to keep CSV manageable
        # 4h data: every candle is fine (1 in 4h)
        sample_rate = 1
        if i % sample_rate == 0:
            equity_curve.append({
                "timestamp": str(ts), "equity": round(equity, 2), "symbol": symbol
            })

        # Drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    # ── Force-close remaining position at last candle ────────────────────
    if qty > 0:
        last = df.iloc[-1]
        last_close = last["close"]
        last_ts = last["timestamp"]

        if side == "LONG":
            gross = qty * last_close
        else:
            gross = qty * (2 * entry_price - last_close)
            if gross < 0:
                gross = 0.0
        exit_fee = gross * FEE_PER_SIDE
        balance += gross - exit_fee

        pnl_pct = ((last_close - entry_price) / entry_price * 100) if side == "LONG" \
            else ((entry_price - last_close) / entry_price * 100)
        pnl_usd = (gross - exit_fee) - notional

        trades.append({
            "symbol": symbol, "side": side, "action": "EXIT",
            "timestamp": str(last_ts), "price": round(last_close, 6),
            "entry_price": round(entry_price, 6),
            "pnl_pct": round(pnl_pct, 4), "pnl_usd": round(pnl_usd, 2),
            "fee": round(exit_fee, 4), "reason": "end_of_data",
            "balance_after": round(balance, 2),
        })
        qty = 0.0

    elapsed = time.time() - t0
    n_exits = len([t for t in trades if t["action"] == "EXIT"])
    sys.stdout.write(
        f"\r  [{symbol}] 100% | ${balance:,.2f} | "
        f"{n_exits} trades | {elapsed:.1f}s            \n"
    )
    sys.stdout.flush()

    return _compute_metrics(
        symbol=symbol,
        initial_balance=initial_balance,
        final_balance=balance,
        trades=trades,
        equity_curve=equity_curve,
        max_drawdown=max_drawdown,
    )


# ---------------------------------------------------------------------------
# 3. Metrics Calculator
# ---------------------------------------------------------------------------

def _compute_metrics(
    symbol: str,
    initial_balance: float,
    final_balance: float,
    trades: list[dict],
    equity_curve: list[dict],
    max_drawdown: float,
) -> dict:
    """Compute all performance metrics from the trade list and equity curve."""

    exits = [t for t in trades if t["action"] == "EXIT"]
    long_exits = [t for t in exits if t["side"] == "LONG"]
    short_exits = [t for t in exits if t["side"] == "SHORT"]
    wins = [t for t in exits if t["pnl_pct"] > 0]
    losses = [t for t in exits if t["pnl_pct"] <= 0]

    total_trades = len(exits)
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0
    avg_win = (sum(t["pnl_pct"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0.0
    best_trade = max((t["pnl_pct"] for t in exits), default=0.0)
    worst_trade = min((t["pnl_pct"] for t in exits), default=0.0)

    # Profit Factor
    gross_profit = sum(t["pnl_usd"] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t["pnl_usd"] for t in losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # Expectancy
    expectancy = 0.0
    if total_trades > 0:
        expectancy = (len(wins)/total_trades) * avg_win + (len(losses)/total_trades) * avg_loss

    total_fees = sum(t.get("fee", 0) for t in trades)

    # Win/Loss streaks
    longest_win = longest_loss = current_win = current_loss = 0
    for t in exits:
        if t["pnl_pct"] > 0:
            current_win += 1; current_loss = 0
            longest_win = max(longest_win, current_win)
        else:
            current_loss += 1; current_win = 0
            longest_loss = max(longest_loss, current_loss)

    # Exit reasons
    exit_reasons: dict[str, int] = {}
    for t in exits:
        r = t.get("reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    # Sharpe / Sortino / Calmar (annualized from hourly equity returns)
    sharpe = sortino = calmar = 0.0
    eq_df = pd.DataFrame(equity_curve)
    if len(eq_df) > 10:
        eq_df["return"] = eq_df["equity"].pct_change()
        returns = eq_df["return"].dropna()
        if len(returns) > 0 and returns.std() > 0:
            # Annualize based on timeframe
            # 4h = 2,190/yr
            ann_factor = math.sqrt(2190)
            sharpe = (returns.mean() / returns.std()) * ann_factor

            downside = returns[returns < 0]
            if len(downside) > 0 and downside.std() > 0:
                sortino = (returns.mean() / downside.std()) * ann_factor

        if max_drawdown > 0:
            total_return = (final_balance - initial_balance) / initial_balance
            ann_return = total_return / 3.0   # 3-year dataset
            calmar = (ann_return * 100) / max_drawdown

    # Monthly returns
    monthly_returns: list[dict] = []
    if len(eq_df) > 10:
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])
        eq_df = eq_df.set_index("timestamp")
        monthly = eq_df["equity"].resample("ME").last().dropna()
        for idx in range(1, len(monthly)):
            m_ret = ((monthly.iloc[idx] - monthly.iloc[idx-1]) / monthly.iloc[idx-1]) * 100
            monthly_returns.append({
                "month": monthly.index[idx].strftime("%Y-%m"),
                "return_pct": round(m_ret, 2),
                "equity": round(monthly.iloc[idx], 2),
            })

    return {
        "symbol": symbol,
        "initial_balance": initial_balance,
        "final_balance": round(final_balance, 2),
        "total_return_pct": round((final_balance - initial_balance) / initial_balance * 100, 2),
        "total_trades": total_trades,
        "long_trades": len(long_exits),
        "short_trades": len(short_exits),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "best_trade_pct": round(best_trade, 4),
        "worst_trade_pct": round(worst_trade, 4),
        "expectancy_pct": round(expectancy, 4),
        "profit_factor": round(profit_factor, 3),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
        "total_fees_paid": round(total_fees, 2),
        "exit_reasons": exit_reasons,
        "trades": trades,
        "equity_curve": equity_curve,
        "monthly_returns": monthly_returns,
    }


# ---------------------------------------------------------------------------
# 4. Report Printer — beautiful ASCII dashboard
# ---------------------------------------------------------------------------

def print_ticker_report(r: dict) -> None:
    """Print a detailed report for a single ticker."""
    print(f"\n  {'=' * 72}")
    print(f"  ||  {r['symbol']:^66}  ||")
    print(f"  {'=' * 72}")

    print(f"\n  +{'─'*34}+{'─'*35}+")
    print(f"  | {'CAPITAL':^32} | {'RISK':^33} |")
    print(f"  +{'─'*34}+{'─'*35}+")
    print(f"  | Initial:    ${r['initial_balance']:>14,.2f}   | Max Drawdown:   {r['max_drawdown_pct']:>8.2f}%        |")
    print(f"  | Final:      ${r['final_balance']:>14,.2f}   | Sharpe Ratio:   {r['sharpe_ratio']:>8.3f}         |")
    print(f"  | Return:     {r['total_return_pct']:>+14.2f}%   | Sortino Ratio:  {r['sortino_ratio']:>8.3f}         |")
    print(f"  | Fees Paid:  ${r['total_fees_paid']:>14,.2f}   | Calmar Ratio:   {r['calmar_ratio']:>8.3f}         |")
    print(f"  |                                  | Profit Factor:  {r['profit_factor']:>8.3f}         |")
    print(f"  +{'─'*34}+{'─'*35}+")

    print(f"\n  +{'─'*34}+{'─'*35}+")
    print(f"  | {'TRADES':^32} | {'PERFORMANCE':^33} |")
    print(f"  +{'─'*34}+{'─'*35}+")
    print(f"  | Total Trades:   {r['total_trades']:>9}       | Best Trade:   {r['best_trade_pct']:>+9.2f}%        |")
    print(f"  | Long Trades:    {r['long_trades']:>9}       | Worst Trade:  {r['worst_trade_pct']:>+9.2f}%        |")
    print(f"  | Short Trades:   {r['short_trades']:>9}       | Avg Win:      {r['avg_win_pct']:>+9.2f}%        |")
    print(f"  | Wins / Losses:  {r['wins']:>4} / {r['losses']:<4}      | Avg Loss:     {r['avg_loss_pct']:>+9.2f}%        |")
    print(f"  | Win Rate:       {r['win_rate']:>8.2f}%      | Expectancy:   {r['expectancy_pct']:>+9.4f}%      |")
    print(f"  +{'─'*34}+{'─'*35}+")

    print(f"\n  +{'─'*34}+{'─'*35}+")
    print(f"  | {'STREAKS':^32} | {'EXIT REASONS':^33} |")
    print(f"  +{'─'*34}+{'─'*35}+")
    er = r["exit_reasons"]
    hs = er.get("hard_stop", 0)
    ts_c = er.get("trailing_stop", 0)
    eod = er.get("end_of_data", 0)
    print(f"  | Longest Win:    {r['longest_win_streak']:>9}       | Hard Stop:    {hs:>9}           |")
    print(f"  | Longest Loss:   {r['longest_loss_streak']:>9}       | Trailing Stop:{ts_c:>9}           |")
    print(f"  |                                  | End of Data:  {eod:>9}           |")
    print(f"  +{'─'*34}+{'─'*35}+")


def print_monthly_table(monthly: list[dict], symbol: str) -> None:
    """Print monthly returns table."""
    if not monthly:
        return
    print(f"\n  Monthly Returns [{symbol}]:")
    print(f"  {'Month':<10} {'Return':>10} {'Equity':>14}")
    print(f"  {'─'*36}")
    for m in monthly:
        ret_str = f"{m['return_pct']:+.2f}%"
        indicator = "+" if m["return_pct"] >= 0 else "-"
        print(f"  {indicator} {m['month']:<8} {ret_str:>10} ${m['equity']:>12,.2f}")


def print_portfolio_summary(results: list[dict]) -> None:
    """Print aggregated portfolio-level stats across all tickers."""
    total_trades = sum(r["total_trades"] for r in results)
    total_wins = sum(r["wins"] for r in results)
    total_losses = sum(r["losses"] for r in results)
    total_fees = sum(r["total_fees_paid"] for r in results)
    avg_drawdown = sum(r["max_drawdown_pct"] for r in results) / len(results)
    avg_sharpe = sum(r["sharpe_ratio"] for r in results) / len(results)
    avg_sortino = sum(r["sortino_ratio"] for r in results) / len(results)
    total_initial = sum(r["initial_balance"] for r in results)
    total_final = sum(r["final_balance"] for r in results)
    win_rate = (total_wins / total_trades * 100) if total_trades else 0

    all_exits: dict[str, int] = {}
    for r in results:
        for reason, count in r["exit_reasons"].items():
            all_exits[reason] = all_exits.get(reason, 0) + count

    best = max(results, key=lambda x: x["total_return_pct"])
    worst = min(results, key=lambda x: x["total_return_pct"])

    pnl = total_final - total_initial
    pnl_pct = (pnl / total_initial) * 100

    print(f"\n\n")
    print(f"  {'=' * 72}")
    print(f"  ||{'PHASE 43.1 — PORTFOLIO STRESS TEST SUMMARY':^70}||")
    print(f"  ||{'GrokSniper Hyper-Trend | 4h | 3 Years | Binance 0.2% Fees':^70}||")
    print(f"  {'=' * 72}")

    print(f"\n  +{'─'*70}+")
    print(f"  | {'PORTFOLIO CAPITAL':^68} |")
    print(f"  +{'─'*70}+")
    print(f"  |  Total Invested (5 tickers x $10,000):   ${total_initial:>18,.2f}          |")
    print(f"  |  Total Final Value:                      ${total_final:>18,.2f}          |")
    indicator = "+" if pnl >= 0 else "-"
    print(f"  |  {indicator} Portfolio P&L:                        ${pnl:>+18,.2f}          |")
    print(f"  |  Portfolio Return:                        {pnl_pct:>+18.2f}%          |")
    print(f"  |  Total Fees Paid:                        ${total_fees:>18,.2f}          |")
    print(f"  +{'─'*70}+")

    print(f"\n  +{'─'*70}+")
    print(f"  | {'AGGREGATED PERFORMANCE':^68} |")
    print(f"  +{'─'*70}+")
    print(f"  |  Total Trades:          {total_trades:>8}                                     |")
    print(f"  |  Total Wins / Losses:   {total_wins:>4} / {total_losses:<4}                                     |")
    print(f"  |  Aggregate Win Rate:    {win_rate:>7.2f}%                                      |")
    print(f"  |  Avg Max Drawdown:      {avg_drawdown:>7.2f}%                                      |")
    print(f"  |  Avg Sharpe Ratio:      {avg_sharpe:>7.3f}                                       |")
    print(f"  |  Avg Sortino Ratio:     {avg_sortino:>7.3f}                                       |")
    print(f"  +{'─'*70}+")

    print(f"\n  +{'─'*70}+")
    print(f"  | {'EXIT REASONS (ALL TICKERS)':^68} |")
    print(f"  +{'─'*70}+")
    for reason, count in sorted(all_exits.items(), key=lambda x: -x[1]):
        pct = count / total_trades * 100 if total_trades else 0
        bar = "#" * int(pct / 2)
        print(f"  |  {reason:<18} {count:>5} ({pct:>5.1f}%)  {bar:<30}        |")
    print(f"  +{'─'*70}+")

    print(f"\n  +{'─'*70}+")
    print(f"  | {'PER-TICKER LEADERBOARD':^68} |")
    print(f"  +{'─'*70}+")
    print(f"  |  {'Ticker':<12} {'Return':>10} {'Trades':>8} {'Win Rate':>10} {'MaxDD':>8} {'Sharpe':>8}  |")
    print(f"  |  {'─'*60}  |")
    sorted_results = sorted(results, key=lambda x: x["total_return_pct"], reverse=True)
    for idx, r in enumerate(sorted_results):
        rank = ["#1", "#2", "#3", "#4", "#5"][idx] if idx < 5 else f"#{idx+1}"
        print(
            f"  |  {rank} {r['symbol']:<10} {r['total_return_pct']:>+9.2f}% "
            f"{r['total_trades']:>8} {r['win_rate']:>9.2f}% "
            f"{r['max_drawdown_pct']:>7.2f}% {r['sharpe_ratio']:>7.3f}  |"
        )
    print(f"  +{'─'*70}+")

    print(f"\n  BEST  PERFORMER: {best['symbol']} ({best['total_return_pct']:+.2f}%)")
    print(f"  WORST PERFORMER: {worst['symbol']} ({worst['total_return_pct']:+.2f}%)")


# ---------------------------------------------------------------------------
# 5. CSV Export
# ---------------------------------------------------------------------------

def save_csvs(results: list[dict]) -> None:
    """Save equity curve and trade log to CSV."""
    all_eq = []
    for r in results:
        all_eq.extend(r["equity_curve"])
    eq_df = pd.DataFrame(all_eq)
    eq_path = OUTPUT_DIR / "stress_test_equity.csv"
    eq_df.to_csv(eq_path, index=False)
    print(f"\n  Equity curve saved to: {eq_path}")

    all_trades = []
    for r in results:
        all_trades.extend(r["trades"])
    tr_df = pd.DataFrame(all_trades)
    tr_path = OUTPUT_DIR / "stress_test_trades.csv"
    tr_df.to_csv(tr_path, index=False)
    print(f"  Trade log saved to:    {tr_path}")

    print(f"\n  Total equity data points: {len(all_eq):,}")
    print(f"  Total trade records:      {len(all_trades):,}")


# ---------------------------------------------------------------------------
# 6. Main Entrypoint
# ---------------------------------------------------------------------------

async def main() -> None:
    t_start = time.time()

    print()
    print("  " + "=" * 72)
    print("  ||" + " PHASE 43.1 — GROKSNIPER OPTIMIZED STRESS TEST ".center(68) + "||")
    print("  ||" + " Hyper-Trend Strategy | 4h | 3-Year Backtest | 0.2% Fees ".center(68) + "||")
    print("  ||" + f" {len(TICKERS)} Tickers x ${INITIAL_BALANCE:,.0f} = ${INITIAL_BALANCE * len(TICKERS):,.0f} Total Capital ".center(68) + "||")
    print("  " + "=" * 72)
    print()

    # Step 1: Download data
    print("  STEP 1: DATA ACQUISITION")
    print("  " + "-" * 40)
    datasets: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        datasets[ticker] = await fetch_ticker_data(
            symbol=ticker, timeframe=TIMEFRAME, days=DAYS_BACK,
        )
    print()

    # Step 1b: Merge BTC Health Guard Data
    btc_df = datasets.get("BTC/USDT")
    if btc_df is not None:
        print("  [HEALTH GUARD] Merging BTC 200 EMA to all tickers...")
        btc_subset = btc_df[["timestamp", "close", "EMA_200"]].copy()
        btc_subset.rename(columns={"close": "BTC_close", "EMA_200": "BTC_EMA_200"}, inplace=True)
        for ticker in TICKERS:
            merged = pd.merge(datasets[ticker], btc_subset, on="timestamp", how="left")
            merged.ffill(inplace=True)
            merged.dropna(inplace=True)
            datasets[ticker] = merged

    # Step 2: Run stress test per ticker
    print("\n  STEP 2: STRATEGY SIMULATION")
    print("  " + "-" * 40)
    results: list[dict] = []
    for ticker in TICKERS:
        result = run_stress_test(
            df=datasets[ticker], symbol=ticker, initial_balance=INITIAL_BALANCE,
        )
        results.append(result)
    print()

    # Step 3: Per-ticker reports
    print("  STEP 3: DETAILED REPORTS")
    print("  " + "-" * 40)
    for r in results:
        print_ticker_report(r)

    # Step 4: Monthly breakdown
    print(f"\n  STEP 4: MONTHLY PERFORMANCE")
    print("  " + "-" * 40)
    for r in results:
        print_monthly_table(r["monthly_returns"], r["symbol"])

    # Step 5: Portfolio summary
    print_portfolio_summary(results)

    # Step 6: Save CSVs
    save_csvs(results)

    total_time = time.time() - t_start
    print(f"\n  Total execution time: {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"  {'=' * 72}")
    print(f"  ||{'STRESS TEST COMPLETE':^70}||")
    print(f"  {'=' * 72}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
