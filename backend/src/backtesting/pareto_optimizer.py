"""
Phase 46 — Multi-Objective Pareto Optimization
================================================
Finds the FULL TRADE-OFF CURVE between Return, Drawdown, and Sharpe.

Instead of one "best" strategy, we produce a Pareto Front:

  ┌─────────────────────────────────────────────────────────────────┐
  │  CONSERVATIVE   →  Minimal drawdown, moderate steady returns    │
  │  BALANCED       →  Sweet-spot risk/reward (Phase 44.3 region)   │
  │  AGGRESSIVE     →  Maximum return, higher drawdown accepted     │
  └─────────────────────────────────────────────────────────────────┘

Algorithm: NSGA-II (Non-dominated Sorting Genetic Algorithm II)
  — Used in Optuna via `NSGAIISampler`
  — Objectives: maximize Avg Return, minimize Max Drawdown
  — After the run, Sharpe is computed and the Pareto front is extracted

Install:  pip install optuna rich
Run:
  cd c:\\Users\\andko\\Desktop\\sniper_bot
  python -m backend.src.backtesting.pareto_optimizer
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

optuna.logging.set_verbosity(optuna.logging.WARNING)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.panel import Panel
    from rich.text import Text
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None  # type: ignore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TICKERS   = ["DOGE/USDT", "SOL/USDT", "XRP/USDT"]
BTC_TICKER = "BTC/USDT"
TIMEFRAME  = "4h"
DAYS_BACK  = 3 * 365        # 3 years of history

N_TRIALS   = 500            # Total NSGA-II population evaluations
N_STARTUP  = 50             # Random warm-up trials before NSGA-II kicks in

INITIAL_BALANCE   = 10_000.0
POSITION_FRACTION = 0.98
FEE_PER_SIDE      = 0.001

CACHE_DIR = Path(__file__).resolve().parent.parent / "scripts" / "cache_stress_test"

# ---------------------------------------------------------------------------
# 1. Data Fetcher (reuses the same cache as stress_test / auto_optimizer)
# ---------------------------------------------------------------------------

async def _fetch(symbol: str, days: int) -> pd.DataFrame:
    import ccxt.async_support as ccxt
    import pandas_ta as ta  # noqa: F401 (imported for DataFrame accessor)

    CACHE_DIR.mkdir(exist_ok=True)
    safe = symbol.replace("/", "_")
    cache_file = CACHE_DIR / f"{safe}_{TIMEFRAME}_{days}d_v2.pkl"

    if cache_file.exists():
        print(f"  [CACHE] {cache_file.name}")
        df = pd.read_pickle(cache_file)
        return df

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )
        print(f"  [DOWNLOAD] {symbol} | {TIMEFRAME} | {days}d ...")
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
        print(f"  [DOWNLOAD] {len(all_ohlcv):,} candles in {time.time()-t0:.0f}s")

        df = pd.DataFrame(all_ohlcv,
                          columns=["timestamp", "open", "high", "low", "close", "volume"])
        df.drop_duplicates(subset="timestamp", inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)

        import pandas_ta as pta
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
        print(f"  [CACHE] Saved → {cache_file.name}")
        return df
    finally:
        await exchange.close()


def _merge_btc(ticker_df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.DataFrame:
    sub = btc_df[["timestamp", "close", "EMA_200"]].copy()
    sub.rename(columns={"close": "BTC_close", "EMA_200": "BTC_EMA_200"}, inplace=True)
    merged = pd.merge(ticker_df, sub, on="timestamp", how="left")
    merged.ffill(inplace=True)
    merged.dropna(inplace=True)
    return merged


# ---------------------------------------------------------------------------
# 2. Silent Backtest Engine
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
    balance = initial_balance
    qty = 0.0; entry_price = 0.0; highest_price = 0.0; lowest_price = 0.0
    notional = 0.0; side = ""; dynamic_sl = 0.0
    wins = 0; losses = 0; total_trades = 0; total_fees = 0.0
    equity_values: list[float] = []
    peak_equity = initial_balance; max_drawdown = 0.0

    closes   = df["close"].values;   highs    = df["high"].values
    lows     = df["low"].values;     volumes  = df["volume"].values
    ema20s   = df["EMA_20"].values;  ema50s   = df["EMA_50"].values
    rsis     = df["RSI_14"].values;  macds    = df["MACD_12_26_9"].values
    sigs     = df["MACDs_12_26_9"].values; vol_smas = df["VOL_SMA_20"].values
    atrs     = df["ATRr_14"].values
    btc_cls  = df["BTC_close"].values; btc_e200 = df["BTC_EMA_200"].values

    n = len(df)
    for i in range(1, n):
        c=closes[i]; h=highs[i]; lo=lows[i]; vol=volumes[i]
        e20=ema20s[i]; e50=ema50s[i]; rsi=rsis[i]
        macd=macds[i]; sig=sigs[i]; vs=vol_smas[i]; atr=atrs[i]
        pm=macds[i-1]; ps=sigs[i-1]; bc=btc_cls[i]; be=btc_e200[i]

        if qty == 0:
            mid = (h + lo) / 2
            # LONG
            if (bc > be and c > e50 and e20 > e50 and pm <= ps and macd > sig
                    and rsi_lower < rsi < rsi_upper
                    and (c - mid) / (h - lo + 1e-9) > min_candle_body_pct
                    and vs > 0 and vol > vs * vol_sma_multiplier):
                spend = balance * POSITION_FRACTION
                fee = spend * FEE_PER_SIDE; total_fees += fee
                notional = spend - fee; qty = notional / c
                balance -= spend; entry_price = c; highest_price = c; lowest_price = c
                side = "LONG"
                dynamic_sl = c - (atr * atr_multiplier if atr > 0 else c * 0.03)
            # SHORT
            elif (bc < be and c < e50 and e20 < e50 and pm >= ps and macd < sig
                    and (100 - rsi_upper) < rsi < (100 - rsi_lower)
                    and (mid - c) / (h - lo + 1e-9) > min_candle_body_pct
                    and vs > 0 and vol > vs * vol_sma_multiplier):
                spend = balance * POSITION_FRACTION
                fee = spend * FEE_PER_SIDE; total_fees += fee
                notional = spend - fee; qty = notional / c
                balance -= spend; entry_price = c; highest_price = c; lowest_price = c
                side = "SHORT"
                dynamic_sl = c + (atr * atr_multiplier if atr > 0 else c * 0.03)

        elif side == "LONG":
            if h > highest_price: highest_price = h
            ep = None
            if lo <= dynamic_sl: ep = dynamic_sl
            elif highest_price >= entry_price * (1 + trailing_activation_pct):
                trig = highest_price * (1 - trailing_pullback_pct)
                if lo <= trig: ep = trig
            if ep is not None:
                gross = qty * ep; fee = gross * FEE_PER_SIDE; total_fees += fee
                balance += gross - fee
                pnl = (ep - entry_price) / entry_price * 100
                total_trades += 1
                wins += 1 if pnl > 0 else 0; losses += 1 if pnl <= 0 else 0
                qty = 0.0; side = ""

        elif side == "SHORT":
            if lo < lowest_price: lowest_price = lo
            ep = None
            if h >= dynamic_sl: ep = dynamic_sl
            elif lowest_price <= entry_price * (1 - trailing_activation_pct):
                trig = lowest_price * (1 + trailing_pullback_pct)
                if h >= trig: ep = trig
            if ep is not None:
                gross = max(qty * (2 * entry_price - ep), 0.0)
                fee = gross * FEE_PER_SIDE; total_fees += fee
                balance += gross - fee
                pnl = (entry_price - ep) / entry_price * 100
                total_trades += 1
                wins += 1 if pnl > 0 else 0; losses += 1 if pnl <= 0 else 0
                qty = 0.0; side = ""

        eq = (balance + qty * c) if side == "LONG" else \
             (balance + qty * max(2 * entry_price - c, 0)) if side == "SHORT" else balance
        equity_values.append(max(eq, 0.0))
        if eq > peak_equity: peak_equity = eq
        dd = (peak_equity - eq) / peak_equity * 100 if peak_equity > 0 else 0.0
        if dd > max_drawdown: max_drawdown = dd

    # Force-close
    if qty > 0:
        last = closes[-1]
        gross = qty * last if side == "LONG" else max(qty * (2 * entry_price - last), 0.0)
        fee = gross * FEE_PER_SIDE; total_fees += fee; balance += gross - fee
        pnl = ((last - entry_price) / entry_price * 100) if side == "LONG" else \
              ((entry_price - last) / entry_price * 100)
        total_trades += 1; wins += 1 if pnl > 0 else 0; losses += 1 if pnl <= 0 else 0

    sharpe = 0.0
    if len(equity_values) > 10:
        arr = np.array(equity_values)
        rets = np.diff(arr) / (arr[:-1] + 1e-9)
        rets = rets[np.isfinite(rets)]
        if len(rets) > 0 and np.std(rets) > 0:
            sharpe = (np.mean(rets) / np.std(rets)) * math.sqrt(2190)

    total_return = (balance - initial_balance) / initial_balance * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    return {
        "total_return_pct": round(total_return, 3),
        "max_drawdown_pct": round(max_drawdown, 3),
        "sharpe_ratio":     round(sharpe, 4),
        "total_trades":     total_trades,
        "win_rate":         round(win_rate, 2),
        "wins":             wins,
    }


# ---------------------------------------------------------------------------
# 3. Multi-Objective Optuna Study (NSGA-II)
# ---------------------------------------------------------------------------

_DATASETS: dict[str, pd.DataFrame] = {}


def _multi_objective(trial: optuna.Trial) -> tuple[float, float]:
    """
    Returns two objectives for Pareto optimisation:
      obj1: -avg_return_pct   (maximise return  → minimise negative)
      obj2: +max_drawdown_pct (minimise drawdown → minimise positive)
    """
    rsi_lower              = trial.suggest_int("rsi_lower", 30, 46)
    rsi_upper              = trial.suggest_int("rsi_upper", 58, 72)
    atr_multiplier         = trial.suggest_float("atr_multiplier", 1.0, 3.0, step=0.1)
    trailing_activation_pct = trial.suggest_float("trailing_activation_pct", 0.02, 0.10, step=0.005)
    trailing_pullback_pct  = trial.suggest_float("trailing_pullback_pct",  0.002, 0.02,  step=0.001)
    vol_sma_multiplier     = trial.suggest_float("vol_sma_multiplier",     0.70,  1.30,  step=0.05)
    min_candle_body_pct    = trial.suggest_float("min_candle_body_pct",    0.00,  0.08,  step=0.01)

    total_return = 0.0; max_dd = 0.0; total_trades = 0; sharpe_sum = 0.0; wins = 0

    for ticker, df in _DATASETS.items():
        m = run_backtest(
            df=df,
            rsi_lower=rsi_lower, rsi_upper=rsi_upper,
            atr_multiplier=atr_multiplier,
            trailing_activation_pct=trailing_activation_pct,
            trailing_pullback_pct=trailing_pullback_pct,
            vol_sma_multiplier=vol_sma_multiplier,
            min_candle_body_pct=min_candle_body_pct,
        )
        total_return += m["total_return_pct"]
        max_dd = max(max_dd, m["max_drawdown_pct"])
        total_trades += m["total_trades"]
        sharpe_sum   += m["sharpe_ratio"]
        wins         += m["wins"]

    n  = max(len(_DATASETS), 1)
    avg_return = total_return / n
    avg_sharpe = sharpe_sum / n
    win_rate   = (wins / total_trades * 100) if total_trades > 0 else 0.0

    # Store rich metadata for the report
    trial.set_user_attr("avg_return",  round(avg_return, 2))
    trial.set_user_attr("max_dd",      round(max_dd,     2))
    trial.set_user_attr("avg_sharpe",  round(avg_sharpe, 3))
    trial.set_user_attr("total_trades", total_trades)
    trial.set_user_attr("win_rate",    round(win_rate,   2))

    # Penalise too few trades
    penalty = 1.0 if total_trades >= 10 else 0.1
    return (-avg_return * penalty, max_dd / penalty)


def run_pareto_study() -> optuna.Study:
    """Run NSGA-II multi-objective Optuna study."""
    sampler = optuna.samplers.NSGAIISampler(
        population_size=40,
        seed=42,
        mutation_prob=0.1,
        crossover_prob=0.9,
    )
    study = optuna.create_study(
        directions=["minimize", "minimize"],  # (-return, drawdown)
        sampler=sampler,
        study_name="GrokSniper_Phase46_Pareto",
    )

    t0 = time.time()
    completed = [0]
    best_score = [1e9]

    def _cb(study, trial):
        completed[0] += 1
        n = completed[0]
        elapsed = time.time() - t0
        eta = (elapsed / n) * (N_TRIALS - n) if n > 0 else 0
        if n % 10 == 0 or n <= 5:
            sys.stdout.write(
                f"\r  Trial {n:>4}/{N_TRIALS} | "
                f"Pareto front size: {len(study.best_trials):>3} | "
                f"ETA: {eta:.0f}s          "
            )
            sys.stdout.flush()

    study.optimize(_multi_objective, n_trials=N_TRIALS, callbacks=[_cb])
    elapsed = time.time() - t0
    print(f"\n\n  Optimisation complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Pareto-optimal solutions found: {len(study.best_trials)}")
    return study


# ---------------------------------------------------------------------------
# 4. Pareto Front Analysis & Strategy Profiles
# ---------------------------------------------------------------------------

def _extract_pareto_profiles(study: optuna.Study) -> dict:
    """
    From the Pareto front, extract three representative strategy profiles:
      - CONSERVATIVE: lowest drawdown on the front
      - AGGRESSIVE:   highest return on the front
      - BALANCED:     closest to the ideal point (min dd + max return)
    """
    pareto = study.best_trials  # list of non-dominated FrozenTrials

    if not pareto:
        return {}

    points = []
    for t in pareto:
        ret = t.user_attrs.get("avg_return", 0)
        dd  = t.user_attrs.get("max_dd", 100)
        sr  = t.user_attrs.get("avg_sharpe", 0)
        tr  = t.user_attrs.get("total_trades", 0)
        wr  = t.user_attrs.get("win_rate", 0)
        points.append({
            "trial":   t,
            "params":  t.params,
            "return":  ret,
            "dd":      dd,
            "sharpe":  sr,
            "trades":  tr,
            "win_rate": wr,
        })

    if not points:
        return {}

    # Sort by drawdown ascending (lowest DD first)
    by_dd  = sorted(points, key=lambda p: p["dd"])
    by_ret = sorted(points, key=lambda p: p["return"], reverse=True)

    conservative = by_dd[0]
    aggressive   = by_ret[0]

    # Balanced: minimise L2 distance to ideal (normalised)
    max_ret = max(p["return"] for p in points) or 1
    min_dd  = min(p["dd"] for p in points) or 0.01
    max_dd  = max(p["dd"] for p in points) or 1

    def _dist(p):
        norm_ret = 1 - (p["return"] / max_ret)           # 0 = best return
        norm_dd  = (p["dd"] - min_dd) / (max_dd - min_dd + 1e-9)  # 0 = best dd
        return math.sqrt(norm_ret**2 + norm_dd**2)

    balanced = min(points, key=_dist)

    return {
        "CONSERVATIVE": conservative,
        "BALANCED":     balanced,
        "AGGRESSIVE":   aggressive,
        "all_pareto":   points,
    }


# ---------------------------------------------------------------------------
# 5. Report Printer
# ---------------------------------------------------------------------------

def _fmt_params(p: dict) -> str:
    return (f"RSI {p['rsi_lower']}-{p['rsi_upper']} | "
            f"ATR×{p['atr_multiplier']:.1f} | "
            f"Trail {p['trailing_activation_pct']*100:.1f}%/{p['trailing_pullback_pct']*100:.1f}%")


def _print_report(profiles: dict, study: optuna.Study) -> None:
    if not profiles:
        print("  ⚠  No Pareto-optimal solutions found. Try increasing N_TRIALS.")
        return

    all_pts = profiles["all_pareto"]

    if _RICH:
        console.print()
        console.rule("[bold cyan]PHASE 46 — MULTI-OBJECTIVE PARETO OPTIMIZATION[/bold cyan]")
        console.print(f"  [dim]NSGA-II | {N_TRIALS} trials | {len(all_pts)} Pareto-optimal solutions[/dim]\n")

        # ── Pareto front table ──────────────────────────────────────────────
        pt = Table(title="Pareto Front (all non-dominated solutions)",
                   box=box.SIMPLE_HEAD, show_header=True, header_style="bold blue")
        pt.add_column("#",       width=4,  justify="right")
        pt.add_column("Return",  width=10, justify="right")
        pt.add_column("MaxDD",   width=9,  justify="right")
        pt.add_column("Sharpe",  width=9,  justify="right")
        pt.add_column("Trades",  width=7,  justify="right")
        pt.add_column("WR%",     width=7,  justify="right")
        pt.add_column("Parameters",         width=50)

        sorted_pts = sorted(all_pts, key=lambda p: p["dd"])
        for i, p in enumerate(sorted_pts, 1):
            ret_col = "green" if p["return"] > 0 else "red"
            pt.add_row(
                str(i),
                f"[{ret_col}]{p['return']:+.1f}%[/{ret_col}]",
                f"{p['dd']:.1f}%",
                f"{p['sharpe']:.3f}",
                str(p["trades"]),
                f"{p['win_rate']:.1f}%",
                _fmt_params(p["params"]),
            )
        console.print(pt)
        console.print()

        # ── Strategy Profiles ───────────────────────────────────────────────
        profile_styles = {
            "CONSERVATIVE": ("🛡️ ", "blue",   "Lowest drawdown — capital preservation first"),
            "BALANCED":     ("⚖️ ", "yellow", "Best risk/reward trade-off on the Pareto front"),
            "AGGRESSIVE":   ("🚀 ", "red",    "Highest return — accept larger drawdowns"),
        }
        for name, (icon, colour, desc) in profile_styles.items():
            prof = profiles[name]
            pars = prof["params"]
            content = (
                f"[dim]{desc}[/dim]\n\n"
                f"  [bold]Return:[/bold]       [{colour}]{prof['return']:+.2f}%[/{colour}]\n"
                f"  [bold]Max Drawdown:[/bold] {prof['dd']:.2f}%\n"
                f"  [bold]Sharpe Ratio:[/bold] {prof['sharpe']:.3f}\n"
                f"  [bold]Total Trades:[/bold] {prof['trades']}\n"
                f"  [bold]Win Rate:[/bold]     {prof['win_rate']:.1f}%\n\n"
                f"  [bold]RSI Range:[/bold]    {pars['rsi_lower']} → {pars['rsi_upper']}\n"
                f"  [bold]ATR Multiplier:[/bold] {pars['atr_multiplier']:.1f}x\n"
                f"  [bold]Trail Activation:[/bold] {pars['trailing_activation_pct']*100:.1f}%\n"
                f"  [bold]Trail Pullback:[/bold]   {pars['trailing_pullback_pct']*100:.1f}%\n"
                f"  [bold]Volume Mult:[/bold]  {pars['vol_sma_multiplier']:.2f}x\n"
                f"  [bold]Body Filter:[/bold]  {pars['min_candle_body_pct']*100:.1f}%\n"
            )
            console.print(Panel(content, title=f"[bold {colour}]{icon} {name}[/bold {colour}]",
                                border_style=colour, expand=False, width=60))
            console.print()

        console.rule()
        console.print("\n  [bold green]RECOMMENDED DEPLOYMENT:[/bold green]")
        b = profiles["BALANCED"]
        console.print(f"  Apply [bold yellow]BALANCED[/bold yellow] profile for the same risk/reward "
                      f"discipline as Phase 44.3, but Pareto-certified.\n")
        console.print(f"  [bold]Balanced Return:[/bold] {b['return']:+.2f}%  |  "
                      f"[bold]MaxDD:[/bold] {b['dd']:.2f}%  |  "
                      f"[bold]Sharpe:[/bold] {b['sharpe']:.3f}\n")
        console.rule()
        console.print()

    else:
        # ASCII fallback
        W = 80
        print()
        print("  " + "=" * W)
        print("  ||" + " PHASE 46 — PARETO OPTIMIZATION REPORT ".center(W - 4) + "||")
        print("  " + "=" * W)

        profile_order = ["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]
        icons = {"CONSERVATIVE": "🛡️ ", "BALANCED": "⚖️ ", "AGGRESSIVE": "🚀"}
        for name in profile_order:
            prof = profiles[name]
            pars = prof["params"]
            print(f"\n  ┌─ {icons[name]} {name} {'─'*(W-8-len(name))}┐")
            print(f"  │  Return: {prof['return']:+.2f}% | MaxDD: {prof['dd']:.2f}% | "
                  f"Sharpe: {prof['sharpe']:.3f} | Trades: {prof['trades']} | "
                  f"WR: {prof['win_rate']:.1f}%")
            print(f"  │  RSI: {pars['rsi_lower']}-{pars['rsi_upper']} | "
                  f"ATR: {pars['atr_multiplier']:.1f}x | "
                  f"Trail: {pars['trailing_activation_pct']*100:.1f}%/{pars['trailing_pullback_pct']*100:.1f}%")
            print(f"  │  Vol: {pars['vol_sma_multiplier']:.2f}x | "
                  f"Body: {pars['min_candle_body_pct']*100:.1f}%")
            print(f"  └{'─'*(W-2)}┘")

        b = profiles["BALANCED"]
        print(f"\n  RECOMMENDED → BALANCED: {b['return']:+.2f}% return | "
              f"{b['dd']:.2f}% MaxDD | {b['sharpe']:.3f} Sharpe")
        print("\n  " + "=" * W)


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

async def main() -> None:
    global _DATASETS

    print()
    print("  " + "=" * 76)
    print("  ||" + " PHASE 46 — MULTI-OBJECTIVE PARETO OPTIMIZATION ".center(72) + "||")
    print("  ||" + " NSGA-II Genetic Algorithm | Maximize Return ↔ Minimize Drawdown ".center(72) + "||")
    print("  ||" + f" {N_TRIALS} trials | {len(TICKERS)} tickers | 3-year dataset ".center(72) + "||")
    print("  " + "=" * 76)

    # ── Data ────────────────────────────────────────────────────────────────
    print("\n  STEP 1: DATA ACQUISITION")
    print("  " + "-" * 50)
    btc_df = await _fetch(BTC_TICKER, DAYS_BACK)
    raw: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        raw[ticker] = await _fetch(ticker, DAYS_BACK)

    print("\n  [HEALTH GUARD] Merging BTC 200-EMA ...")
    for ticker in TICKERS:
        merged = _merge_btc(raw[ticker], btc_df)
        _DATASETS[ticker] = merged
        print(f"    {ticker}: {len(merged):,} candles")

    # ── Optimise ────────────────────────────────────────────────────────────
    print("\n  STEP 2: NSGA-II MULTI-OBJECTIVE OPTIMISATION")
    print("  " + "-" * 50)
    print(f"  Running {N_TRIALS} trials — optimising Return ↔ Drawdown simultaneously...\n")

    study = run_pareto_study()

    # ── Extract profiles ────────────────────────────────────────────────────
    print("\n  STEP 3: PARETO FRONT ANALYSIS")
    print("  " + "-" * 50)
    profiles = _extract_pareto_profiles(study)

    _print_report(profiles, study)


if __name__ == "__main__":
    asyncio.run(main())
