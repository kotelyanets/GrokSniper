"""
Phase 45 — Walk-Forward Validation (WFV) Engine
=================================================
Rigorously tests whether Phase 44.3 parameters are ROBUST or merely curve-fitted
to historical data.

Methodology (Anchored Rolling Windows):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Window 1:  [IS: 30 days]              [OOS: 10 days]                │
  │ Window 2:      [IS: 30 days]              [OOS: 10 days]            │
  │ Window 3:          [IS: 30 days]              [OOS: 10 days]        │
  │ ...                                                                 │
  └─────────────────────────────────────────────────────────────────────┘

  IS  (In-Sample) : Optuna finds the BEST parameters for that period.
  OOS (Out-of-Sample): Those exact best params are applied FORWARD in time.
  The OOS results are what matter — they simulate live trading.

Verdict:
  Aggregated OOS PnL > 0  →  ✅  ROBUST
  Aggregated OOS PnL ≤ 0  →  ❌  POSSIBLY OVERFITTED

Install:  pip install optuna rich
Run:
  cd c:\\Users\\andko\\Desktop\\sniper_bot
  python -m backend.src.backtesting.walk_forward
"""

import asyncio
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import pandas_ta as ta

# ── Suppress Optuna's per-trial chatter ─────────────────────────────────────
optuna.logging.set_verbosity(optuna.logging.WARNING)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Try to import rich for pretty tables; fall back to plain ASCII ───────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TICKERS = ["DOGE/USDT", "SOL/USDT"]   # Most volatile — best for WFV
BTC_TICKER = "BTC/USDT"
TIMEFRAME = "4h"

TOTAL_DAYS = 120       # Total history to fetch (days)
IS_DAYS    = 30        # In-Sample window length (days)
OOS_DAYS   = 10        # Out-Of-Sample window length (days)
STEP_DAYS  = 10        # How many days to slide the window forward per iteration
N_TRIALS   = 75        # Optuna trials per IS window (quick but effective)

CANDLES_PER_DAY = 6    # 4h timeframe = 6 candles per day

INITIAL_BALANCE  = 10_000.0
POSITION_FRACTION = 0.98
FEE_PER_SIDE     = 0.001

CACHE_DIR = Path(__file__).resolve().parent / "cache_wfv"

# ---------------------------------------------------------------------------
# 1.  Data Fetcher
# ---------------------------------------------------------------------------

async def _fetch(symbol: str, days: int) -> pd.DataFrame:
    """Download OHLCV from Binance & cache locally."""
    import ccxt.async_support as ccxt

    CACHE_DIR.mkdir(exist_ok=True)
    safe = symbol.replace("/", "_")
    cache_file = CACHE_DIR / f"{safe}_{TIMEFRAME}_{days}d_wfv.pkl"

    if cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_h < 23:          # Treat cache as fresh for 23 hours
            print(f"    [CACHE] {cache_file.name} ({age_h:.1f}h old)")
            df = pd.read_pickle(cache_file)
            print(f"    [CACHE]  → {len(df):,} candles")
            return df

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp() * 1000
        )
        print(f"    [DOWNLOAD] {symbol} | {TIMEFRAME} | {days}d ...")

        all_ohlcv: list = []
        t0 = time.time()
        while True:
            batch = await exchange.fetch_ohlcv(
                symbol, timeframe=TIMEFRAME, since=since_ms, limit=1000
            )
            if not batch:
                break
            all_ohlcv.extend(batch)
            if len(batch) < 1000:
                break
            since_ms = batch[-1][0] + 1
            await asyncio.sleep(0.12)

        print(f"    [DOWNLOAD] {len(all_ohlcv):,} candles in {time.time()-t0:.0f}s")

        df = pd.DataFrame(all_ohlcv,
                          columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.drop_duplicates(subset="timestamp", inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)

        # ── Indicators ──────────────────────────────────────────────────────
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.atr(length=14, append=True)
        df["VOL_SMA_20"] = df["volume"].rolling(20).mean()
        df.dropna(inplace=True)
        df.reset_index(inplace=True)

        df.to_pickle(cache_file)
        print(f"    [CACHE] Saved → {cache_file.name}")
        return df
    finally:
        await exchange.close()


def _merge_btc_health(ticker_df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.DataFrame:
    """Attach BTC 200-EMA health guard columns to a ticker DataFrame."""
    btc_sub = btc_df[["timestamp", "close", "EMA_200"]].copy()
    btc_sub.rename(columns={"close": "BTC_close", "EMA_200": "BTC_EMA_200"}, inplace=True)
    merged = pd.merge(ticker_df, btc_sub, on="timestamp", how="left")
    merged.ffill(inplace=True)
    merged.dropna(inplace=True)
    return merged


# ---------------------------------------------------------------------------
# 2.  Parameterised Backtest Engine  (same as auto_optimizer.run_backtest)
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    rsi_lower: int,
    rsi_upper: int,
    atr_multiplier: float,
    trailing_activation_pct: float,
    trailing_pullback_pct: float,
    vol_sma_multiplier: float,
    min_candle_body_pct: float,
    initial_balance: float = INITIAL_BALANCE,
) -> dict:
    """Silent backtest on the given slice. Returns metrics dict."""
    balance = initial_balance
    qty = 0.0
    entry_price = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    notional = 0.0
    side = ""
    dynamic_sl = 0.0

    wins = 0
    losses = 0
    total_trades = 0
    total_fees = 0.0
    equity_values: list[float] = []
    peak_equity = initial_balance
    max_drawdown = 0.0

    closes   = df["close"].values
    highs    = df["high"].values
    lows     = df["low"].values
    volumes  = df["volume"].values
    ema20s   = df["EMA_20"].values
    ema50s   = df["EMA_50"].values
    rsis     = df["RSI_14"].values
    macds    = df["MACD_12_26_9"].values
    sigs     = df["MACDs_12_26_9"].values
    vol_smas = df["VOL_SMA_20"].values
    atrs     = df["ATRr_14"].values
    btc_cls  = df["BTC_close"].values
    btc_e200 = df["BTC_EMA_200"].values

    n = len(df)
    for i in range(1, n):
        close  = closes[i];  high   = highs[i];   low    = lows[i]
        volume = volumes[i]; ema20  = ema20s[i];   ema50  = ema50s[i]
        rsi    = rsis[i];    macd   = macds[i];    signal = sigs[i]
        vol_sma = vol_smas[i]; atr  = atrs[i]
        p_macd = macds[i-1]; p_sig  = sigs[i-1]
        btc_c  = btc_cls[i]; btc_e  = btc_e200[i]

        if qty == 0:
            entered = False
            # — LONG —
            mid = (high + low) / 2
            if (btc_c > btc_e
                    and close > ema50 and ema20 > ema50
                    and (p_macd <= p_sig) and (macd > signal)
                    and rsi_lower < rsi < rsi_upper
                    and (close - mid) / (high - low + 1e-9) > min_candle_body_pct
                    and vol_sma > 0 and volume > vol_sma * vol_sma_multiplier):
                spend = balance * POSITION_FRACTION
                fee   = spend * FEE_PER_SIDE
                total_fees += fee
                notional = spend - fee
                qty = notional / close
                balance -= spend
                entry_price = close
                highest_price = close
                lowest_price = close
                side = "LONG"
                dynamic_sl = close - (atr * atr_multiplier if atr > 0 else close * 0.03)
                entered = True
            # — SHORT —
            if not entered:
                mid = (high + low) / 2
                if (btc_c < btc_e
                        and close < ema50 and ema20 < ema50
                        and (p_macd >= p_sig) and (macd < signal)
                        and (100 - rsi_upper) < rsi < (100 - rsi_lower)
                        and (mid - close) / (high - low + 1e-9) > min_candle_body_pct
                        and vol_sma > 0 and volume > vol_sma * vol_sma_multiplier):
                    spend = balance * POSITION_FRACTION
                    fee = spend * FEE_PER_SIDE
                    total_fees += fee
                    notional = spend - fee
                    qty = notional / close
                    balance -= spend
                    entry_price = close
                    highest_price = close
                    lowest_price = close
                    side = "SHORT"
                    dynamic_sl = close + (atr * atr_multiplier if atr > 0 else close * 0.03)

        elif side == "LONG":
            if high > highest_price:
                highest_price = high
            exit_price = None
            if low <= dynamic_sl:
                exit_price = dynamic_sl
            elif highest_price >= entry_price * (1.0 + trailing_activation_pct):
                trig = highest_price * (1.0 - trailing_pullback_pct)
                if low <= trig:
                    exit_price = trig
            if exit_price is not None:
                gross = qty * exit_price
                fee   = gross * FEE_PER_SIDE
                total_fees += fee
                balance += gross - fee
                pnl = (exit_price - entry_price) / entry_price * 100
                total_trades += 1
                wins += 1 if pnl > 0 else 0
                losses += 1 if pnl <= 0 else 0
                qty = 0.0; side = ""

        elif side == "SHORT":
            if low < lowest_price:
                lowest_price = low
            exit_price = None
            if high >= dynamic_sl:
                exit_price = dynamic_sl
            elif lowest_price <= entry_price * (1.0 - trailing_activation_pct):
                trig = lowest_price * (1.0 + trailing_pullback_pct)
                if high >= trig:
                    exit_price = trig
            if exit_price is not None:
                gross = (2 * entry_price - exit_price) * qty
                if gross < 0:
                    gross = 0.0
                fee = gross * FEE_PER_SIDE
                total_fees += fee
                balance += gross - fee
                pnl = (entry_price - exit_price) / entry_price * 100
                total_trades += 1
                wins += 1 if pnl > 0 else 0
                losses += 1 if pnl <= 0 else 0
                qty = 0.0; side = ""

        # Equity for drawdown
        if qty > 0:
            eq = balance + qty * close if side == "LONG" else balance + qty * (2 * entry_price - close)
        else:
            eq = balance
        eq = max(eq, 0.0)
        equity_values.append(eq)
        if eq > peak_equity:
            peak_equity = eq
        dd = (peak_equity - eq) / peak_equity * 100 if peak_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd

    # Force-close open position at end of slice
    if qty > 0:
        last = closes[-1]
        if side == "LONG":
            gross = qty * last
        else:
            gross = max(qty * (2 * entry_price - last), 0.0)
        fee = gross * FEE_PER_SIDE
        total_fees += fee
        balance += gross - fee
        pnl = ((last - entry_price) / entry_price * 100) if side == "LONG" \
            else ((entry_price - last) / entry_price * 100)
        total_trades += 1
        wins += 1 if pnl > 0 else 0
        losses += 1 if pnl <= 0 else 0

    # Sharpe
    sharpe = 0.0
    if len(equity_values) > 10:
        arr = np.array(equity_values)
        rets = np.diff(arr) / (arr[:-1] + 1e-9)
        rets = rets[np.isfinite(rets)]
        if len(rets) > 0 and np.std(rets) > 0:
            sharpe = (np.mean(rets) / np.std(rets)) * math.sqrt(2190)

    total_return_pct = (balance - initial_balance) / initial_balance * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "total_return_pct": round(total_return_pct, 3),
        "total_trades":     total_trades,
        "wins":             wins,
        "win_rate":         round(win_rate, 2),
        "max_drawdown_pct": round(max_drawdown, 3),
        "sharpe_ratio":     round(sharpe, 4),
    }


# ---------------------------------------------------------------------------
# 3.  IS Optimiser (mini-Optuna study per window)
# ---------------------------------------------------------------------------

def _objective_for_slice(trial: optuna.Trial, datasets: dict) -> float:
    """Optuna objective that runs across all datasets on the given (IS) slices."""
    rsi_lower              = trial.suggest_int("rsi_lower", 30, 46)
    rsi_upper              = trial.suggest_int("rsi_upper", 58, 72)
    atr_multiplier         = trial.suggest_float("atr_multiplier", 1.0, 3.0, step=0.1)
    trailing_activation_pct = trial.suggest_float("trailing_activation_pct", 0.02, 0.10, step=0.005)
    trailing_pullback_pct  = trial.suggest_float("trailing_pullback_pct",  0.002, 0.02,  step=0.001)
    vol_sma_multiplier     = trial.suggest_float("vol_sma_multiplier",     0.70,  1.30,  step=0.05)
    min_candle_body_pct    = trial.suggest_float("min_candle_body_pct",    0.00,  0.08,  step=0.01)

    total_return  = 0.0
    max_dd        = 0.0
    total_trades  = 0
    total_wins    = 0
    sharpe_sum    = 0.0

    for ticker, df in datasets.items():
        m = run_backtest(
            df=df,
            rsi_lower=rsi_lower,
            rsi_upper=rsi_upper,
            atr_multiplier=atr_multiplier,
            trailing_activation_pct=trailing_activation_pct,
            trailing_pullback_pct=trailing_pullback_pct,
            vol_sma_multiplier=vol_sma_multiplier,
            min_candle_body_pct=min_candle_body_pct,
        )
        total_return += m["total_return_pct"]
        max_dd = max(max_dd, m["max_drawdown_pct"])
        total_trades += m["total_trades"]
        total_wins   += m["wins"]
        sharpe_sum   += m["sharpe_ratio"]

    n_tickers = max(len(datasets), 1)
    avg_ret   = total_return / n_tickers
    avg_sharpe = sharpe_sum / n_tickers
    if max_dd < 0.01:
        max_dd = 0.01

    score = (avg_ret / max_dd) * 0.8 + max(avg_sharpe, 0) * 0.2
    if total_trades < 5:
        score *= 0.1
    return score


def _run_is_optimisation(is_datasets: dict) -> dict:
    """Run a short Optuna study on IS data → return best params dict."""
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(
        lambda t: _objective_for_slice(t, is_datasets),
        n_trials=N_TRIALS,
        show_progress_bar=False,
    )
    return study.best_params


# ---------------------------------------------------------------------------
# 4.  Walk-Forward Engine
# ---------------------------------------------------------------------------

def _slice_df(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Return rows where timestamp ∈ [start, end)."""
    mask = (df["timestamp"] >= start) & (df["timestamp"] < end)
    return df[mask].copy().reset_index(drop=True)


def run_walk_forward(all_data: dict) -> list[dict]:
    """
    Executes the rolling WFV windows.
    Returns a list of result dicts — one per OOS window.
    """
    # Use DOGE reference or first ticker to anchor dates
    ref_df = next(iter(all_data.values()))
    earliest = ref_df["timestamp"].min()
    latest   = ref_df["timestamp"].max()

    total_days_avail = (latest - earliest).days
    print(f"\n  Data range: {earliest.date()} → {latest.date()} "
          f"({total_days_avail} days available)\n")

    results: list[dict] = []
    window_num = 0

    is_td  = timedelta(days=IS_DAYS)
    oos_td = timedelta(days=OOS_DAYS)
    step   = timedelta(days=STEP_DAYS)

    # Start from the beginning, step forward
    is_start = earliest
    while True:
        is_end  = is_start + is_td
        oos_end = is_end   + oos_td

        if oos_end > latest + timedelta(days=1):
            break  # Not enough data for a full OOS window

        window_num += 1
        print(f"  ┌─ Window {window_num} ─────────────────────────────────────────────────────┐")
        print(f"  │  IS:  [{is_start.date()} → {is_end.date()}]  ({IS_DAYS}d)")
        print(f"  │  OOS: [{is_end.date()} → {oos_end.date()}]  ({OOS_DAYS}d)")

        # Build IS slices for each ticker
        is_slices = {}
        for ticker, df in all_data.items():
            sl = _slice_df(df, is_start, is_end)
            if len(sl) >= 20:        # Need minimum candles for indicators to warm up
                is_slices[ticker] = sl

        if not is_slices:
            print(f"  │  ⚠  Skipping — insufficient IS data")
            print(f"  └─────────────────────────────────────────────────────────────────────┘\n")
            is_start += step
            continue

        # ── IS Optimisation ─────────────────────────────────────────────────
        t_opt = time.time()
        print(f"  │  Running Optuna IS optimisation ({N_TRIALS} trials) ...", end="", flush=True)
        best_params = _run_is_optimisation(is_slices)
        print(f"  done in {time.time()-t_opt:.1f}s")

        # Show best IS params
        rsi_str  = f"RSI {best_params['rsi_lower']}-{best_params['rsi_upper']}"
        atr_str  = f"ATR×{best_params['atr_multiplier']:.1f}"
        tail_str = (f"Trail {best_params['trailing_activation_pct']*100:.1f}%"
                    f"/{best_params['trailing_pullback_pct']*100:.1f}%")
        print(f"  │  Best IS params → {rsi_str} | {atr_str} | {tail_str}")

        # IS performance (for interest)
        is_perf: list[float] = []
        for ticker, sl in is_slices.items():
            m = run_backtest(df=sl, **best_params)
            is_perf.append(m["total_return_pct"])
        avg_is_return = sum(is_perf) / len(is_perf) if is_perf else 0.0
        print(f"  │  IS avg return: {avg_is_return:+.2f}%")

        # ── OOS testing ─────────────────────────────────────────────────────
        oos_returns:  list[float] = []
        oos_drawdowns: list[float] = []
        oos_sharpes:  list[float] = []
        oos_trades_total = 0
        oos_wins_total   = 0

        for ticker, df in all_data.items():
            oos_sl = _slice_df(df, is_end, oos_end)
            if len(oos_sl) < 5:
                continue
            m = run_backtest(df=oos_sl, **best_params)
            oos_returns.append(m["total_return_pct"])
            oos_drawdowns.append(m["max_drawdown_pct"])
            oos_sharpes.append(m["sharpe_ratio"])
            oos_trades_total += m["total_trades"]
            oos_wins_total   += m["wins"]

        avg_oos_return   = sum(oos_returns) / len(oos_returns) if oos_returns else 0.0
        avg_oos_drawdown = max(oos_drawdowns) if oos_drawdowns else 0.0
        avg_oos_sharpe   = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
        oos_win_rate = (oos_wins_total / oos_trades_total * 100) if oos_trades_total > 0 else 0.0

        emoji = "✅" if avg_oos_return > 0 else "❌"
        print(f"  │  OOS result:  {emoji} {avg_oos_return:+.2f}% | "
              f"MaxDD {avg_oos_drawdown:.2f}% | Sharpe {avg_oos_sharpe:.3f} | "
              f"{oos_trades_total} trades ({oos_win_rate:.1f}% WR)")
        print(f"  └─────────────────────────────────────────────────────────────────────┘\n")

        results.append({
            "window":          window_num,
            "is_start":        str(is_start.date()),
            "is_end":          str(is_end.date()),
            "oos_start":       str(is_end.date()),
            "oos_end":         str(oos_end.date()),
            "best_params":     best_params,
            "is_avg_return":   round(avg_is_return, 3),
            "oos_avg_return":  round(avg_oos_return, 3),
            "oos_max_dd":      round(avg_oos_drawdown, 3),
            "oos_sharpe":      round(avg_oos_sharpe, 4),
            "oos_trades":      oos_trades_total,
            "oos_win_rate":    round(oos_win_rate, 2),
        })

        is_start += step   # Slide forward

    return results


# ---------------------------------------------------------------------------
# 5.  Rich Report Printer
# ---------------------------------------------------------------------------

def _print_report(results: list[dict]) -> None:
    if not results:
        print("\n  ⚠  No WFV windows completed — try fetching more history.")
        return

    # Summary stats
    all_oos = [r["oos_avg_return"] for r in results]
    all_dd  = [r["oos_max_dd"]     for r in results]
    all_sr  = [r["oos_sharpe"]     for r in results]
    all_tr  = [r["oos_trades"]     for r in results]
    all_wr  = [r["oos_win_rate"]   for r in results]

    agg_pnl     = sum(all_oos)                                # Aggregated total
    avg_pnl     = agg_pnl / len(all_oos)                      # Avg per window
    avg_dd      = sum(all_dd) / len(all_dd)
    avg_sharpe  = sum(all_sr) / len(all_sr)
    total_trades = sum(all_tr)
    avg_wr      = sum(all_wr) / len(all_wr) if all_wr else 0.0
    profitable_windows = sum(1 for r in all_oos if r > 0)
    win_pct = profitable_windows / len(results) * 100

    verdict = "✅  ROBUST — Strategy generalises to unseen data!" if avg_pnl > 0 else \
              "❌  POSSIBLY OVERFITTED — Parameters do not generalise!"

    if _RICH:
        console.print()
        console.rule("[bold cyan]PHASE 45 — WALK-FORWARD VALIDATION REPORT[/bold cyan]")
        console.print()

        # Per-window table
        table = Table(
            title="OOS Performance Per Window",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("#",           style="cyan",    justify="right",  width=4)
        table.add_column("IS Period",   style="white",   justify="center", width=24)
        table.add_column("OOS Period",  style="white",   justify="center", width=24)
        table.add_column("OOS PnL",     justify="right", width=10)
        table.add_column("MaxDD",       justify="right", width=8)
        table.add_column("Sharpe",      justify="right", width=8)
        table.add_column("Trades",      justify="right", width=7)
        table.add_column("WR%",         justify="right", width=7)

        for r in results:
            pnl = r["oos_avg_return"]
            pnl_style = "green" if pnl > 0 else "red"
            table.add_row(
                str(r["window"]),
                f"{r['is_start']} → {r['is_end']}",
                f"{r['oos_start']} → {r['oos_end']}",
                f"[{pnl_style}]{pnl:+.2f}%[/{pnl_style}]",
                f"{r['oos_max_dd']:.2f}%",
                f"{r['oos_sharpe']:.3f}",
                str(r["oos_trades"]),
                f"{r['oos_win_rate']:.1f}%",
            )
        console.print(table)
        console.print()

        # Summary panel
        summary_table = Table(
            title="Aggregated OOS Statistics",
            box=box.DOUBLE_EDGE,
            show_header=False,
        )
        summary_table.add_column("Metric", style="bold yellow", width=38)
        summary_table.add_column("Value",  justify="right",     width=20)

        verdict_colour = "green" if avg_pnl > 0 else "red"
        summary_table.add_row("Windows Completed",       str(len(results)))
        summary_table.add_row("Profitable Windows",      f"{profitable_windows}/{len(results)} ({win_pct:.0f}%)")
        summary_table.add_row("Avg OOS PnL / Window",    f"{avg_pnl:+.2f}%")
        summary_table.add_row("Aggregated OOS PnL (Σ)", f"{agg_pnl:+.2f}%")
        summary_table.add_row("Avg Max Drawdown",        f"{avg_dd:.2f}%")
        summary_table.add_row("Avg Sharpe Ratio",        f"{avg_sharpe:.3f}")
        summary_table.add_row("Total OOS Trades",        str(total_trades))
        summary_table.add_row("Avg Win Rate",            f"{avg_wr:.1f}%")
        console.print(summary_table)
        console.print()
        console.rule()
        console.print(f"\n  [bold {verdict_colour}]FINAL VERDICT: {verdict}[/bold {verdict_colour}]\n")
        console.rule()
        console.print()

    else:
        # ── Pure ASCII fallback ──────────────────────────────────────────────
        W = 82
        print()
        print("  " + "=" * W)
        print("  ||" + " PHASE 45 — WALK-FORWARD VALIDATION REPORT ".center(W - 4) + "||")
        print("  " + "=" * W)

        print(f"\n  +{'─'*8}+{'─'*26}+{'─'*26}+{'─'*10}+{'─'*8}+{'─'*8}+{'─'*8}+{'─'*8}+")
        hdr = (f"  |{'#':^8}|{'IS Period':^26}|{'OOS Period':^26}|"
               f"{'OOS PnL':^10}|{'MaxDD':^8}|{'Sharpe':^8}|{'Trades':^8}|{'WR%':^8}|")
        print(hdr)
        print(f"  +{'─'*8}+{'─'*26}+{'─'*26}+{'─'*10}+{'─'*8}+{'─'*8}+{'─'*8}+{'─'*8}+")

        for r in results:
            sign  = "+" if r["oos_avg_return"] >= 0 else ""
            glyph = "✅" if r["oos_avg_return"] > 0 else "❌"
            print(
                f"  |{r['window']:^8}|"
                f"{r['is_start']+' → '+r['is_end']:^26}|"
                f"{r['oos_start']+' → '+r['oos_end']:^26}|"
                f"{sign+str(round(r['oos_avg_return'],2))+'%':^10}|"
                f"{str(r['oos_max_dd'])+'%':^8}|"
                f"{str(r['oos_sharpe']):^8}|"
                f"{r['oos_trades']:^8}|"
                f"{str(r['oos_win_rate'])+'%':^8}| {glyph}"
            )
        print(f"  +{'─'*8}+{'─'*26}+{'─'*26}+{'─'*10}+{'─'*8}+{'─'*8}+{'─'*8}+{'─'*8}+")

        print(f"\n  +{'─'*80}+")
        print(f"  | {'AGGREGATED OOS STATISTICS':^78} |")
        print(f"  +{'─'*80}+")
        print(f"  |  Windows Completed          : {len(results):<48} |")
        print(f"  |  Profitable Windows         : {profitable_windows}/{len(results)} ({win_pct:.0f}%){'':<38} |")
        print(f"  |  Avg OOS PnL / Window       : {avg_pnl:+.2f}%{'':<44} |")
        print(f"  |  Aggregated OOS PnL (sum)   : {agg_pnl:+.2f}%{'':<44} |")
        print(f"  |  Avg Max Drawdown           : {avg_dd:.2f}%{'':<45} |")
        print(f"  |  Avg Sharpe Ratio           : {avg_sharpe:.3f}{'':<45} |")
        print(f"  |  Total OOS Trades           : {total_trades:<48} |")
        print(f"  |  Avg Win Rate               : {avg_wr:.1f}%{'':<45} |")
        print(f"  +{'─'*80}+")

        border_char = "✅" if avg_pnl > 0 else "❌"
        print()
        print("  " + "=" * W)
        print(f"  ||  {border_char}  FINAL VERDICT: {verdict:<{W-11}}||")
        print("  " + "=" * W)
        print()


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print()
    print("  " + "=" * 76)
    print("  ||" + " PHASE 45 — WALK-FORWARD VALIDATION ENGINE ".center(72) + "||")
    print("  ||" + f" IS={IS_DAYS}d | OOS={OOS_DAYS}d | Step={STEP_DAYS}d | {N_TRIALS} trials/window ".center(72) + "||")
    print("  ||" + f" Tickers: {', '.join(TICKERS)} ".center(72) + "||")
    print("  " + "=" * 76)

    # ── 1. Fetch data ────────────────────────────────────────────────────────
    print("\n  STEP 1: DATA ACQUISITION")
    print("  " + "-" * 50)

    raw_data: dict[str, pd.DataFrame] = {}
    btc_df = await _fetch(BTC_TICKER, TOTAL_DAYS + 35)   # Extra buffer for BTC health guard
    raw_data[BTC_TICKER] = btc_df

    for ticker in TICKERS:
        raw_data[ticker] = await _fetch(ticker, TOTAL_DAYS + 35)

    print("\n  [HEALTH GUARD] Merging BTC 200-EMA to all tickers...")
    all_data: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        all_data[ticker] = _merge_btc_health(raw_data[ticker], btc_df)
        print(f"    {ticker}: {len(all_data[ticker]):,} candles after merge")

    # ── 2. Walk-Forward loop ─────────────────────────────────────────────────
    print("\n  STEP 2: ROLLING WINDOW OPTIMISATION + OOS TESTING")
    print("  " + "-" * 50)
    t0 = time.time()

    results = run_walk_forward(all_data)

    elapsed = time.time() - t0
    print(f"\n  WFV completed in {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # ── 3. Report ────────────────────────────────────────────────────────────
    _print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
