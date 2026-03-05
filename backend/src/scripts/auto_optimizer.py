"""
Phase 44.2 — Deep Self-Optimizing Backtest Engine (Optuna)
===========================================================
Expanded search space: 7 parameters, 500 Bayesian trials.
Sampler: TPE warm-start → CMA-ES (best-in-class continuous optimizer).

Install:   pip install optuna
Run:
  cd c:\\Users\\andko\\Desktop\\sniper_bot
  python -m backend.src.scripts.auto_optimizer
"""

import asyncio
import sys
import time
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta
import optuna

# suppress Optuna trial-level logs (we print our own progress)
optuna.logging.set_verbosity(optuna.logging.WARNING)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TICKERS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
TIMEFRAME = "4h"
DAYS_BACK = 3 * 365
INITIAL_BALANCE = 10_000.0
POSITION_FRACTION = 0.98
FEE_PER_SIDE = 0.001

CACHE_DIR = Path(__file__).resolve().parent / "cache_stress_test"

# ---------------------------------------------------------------------------
# 1.  Data Fetcher (same as stress_test.py, downloads once & caches)
# ---------------------------------------------------------------------------

async def fetch_ticker_data(
    symbol: str,
    timeframe: str = "4h",
    days: int = 1095,
) -> pd.DataFrame:
    """Download 4h candles from Binance. Cached as pickle."""
    import ccxt.async_support as ccxt

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

        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
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
# 2.  Parameterised Backtest Engine  (silent, returns metrics only)
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    rsi_lower: int,
    rsi_upper: int,
    atr_multiplier: float,
    trailing_activation_pct: float,
    trailing_pullback_pct: float,
    vol_sma_multiplier: float,
    min_candle_body_pct: float,
    initial_balance: float = 10_000.0,
) -> dict:
    """
    Silent version of the stress-test engine with tuneable parameters.
    Returns a dict with key metrics (no print output).
    """
    balance = initial_balance
    qty = 0.0
    entry_price = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    notional = 0.0
    side = ""
    dynamic_sl = 0.0
    entry_spend = 0.0

    wins = 0
    losses = 0
    total_trades = 0
    total_pnl_pct = 0.0
    total_fees = 0.0

    equity_values: list[float] = []
    peak_equity = initial_balance
    max_drawdown = 0.0

    EMA20 = "EMA_20"
    EMA50 = "EMA_50"
    RSI   = "RSI_14"
    MACD_L = "MACD_12_26_9"
    MACD_S = "MACDs_12_26_9"
    VOL_SMA = "VOL_SMA_20"
    ATR    = "ATRr_14"

    # Pre-compute numpy arrays for speed
    closes   = df["close"].values
    highs    = df["high"].values
    lows     = df["low"].values
    volumes  = df["volume"].values
    ema20s   = df[EMA20].values
    ema50s   = df[EMA50].values
    rsis     = df[RSI].values
    macds    = df[MACD_L].values
    signals  = df[MACD_S].values
    vol_smas = df[VOL_SMA].values
    atrs     = df[ATR].values
    btc_closes  = df["BTC_close"].values
    btc_ema200s = df["BTC_EMA_200"].values

    total_rows = len(df)

    for i in range(1, total_rows):
        close    = closes[i]
        high     = highs[i]
        low      = lows[i]
        volume   = volumes[i]
        ema20    = ema20s[i]
        ema50    = ema50s[i]
        rsi      = rsis[i]
        macd     = macds[i]
        signal   = signals[i]
        vol_sma  = vol_smas[i]
        atr      = atrs[i]
        prev_macd   = macds[i - 1]
        prev_signal = signals[i - 1]
        btc_close   = btc_closes[i]
        btc_ema_200 = btc_ema200s[i]

        # ── NO POSITION — check entries ──────────────────────────────────
        if qty == 0:
            entered = False

            # LONG
            cond_btc   = btc_close > btc_ema_200
            cond_trend = close > ema50 and ema20 > ema50
            cond_macd  = (prev_macd <= prev_signal) and (macd > signal)
            cond_rsi   = rsi_lower < rsi < rsi_upper
            candle_mid = (high + low) / 2
            cond_body  = (close - candle_mid) / (high - low + 1e-9) > min_candle_body_pct
            cond_vol   = vol_sma > 0 and volume > vol_sma * vol_sma_multiplier

            if cond_btc and cond_trend and cond_macd and cond_rsi and cond_body and cond_vol:
                spend = balance * POSITION_FRACTION
                entry_fee = spend * FEE_PER_SIDE
                total_fees += entry_fee
                notional = spend - entry_fee
                qty = notional / close
                balance -= spend
                entry_price = close
                highest_price = close
                lowest_price = close
                side = "LONG"
                atr_dist = atr * atr_multiplier if atr > 0 else close * 0.03
                dynamic_sl = close - atr_dist
                entered = True

            # SHORT
            if not entered:
                cond_btc_s   = btc_close < btc_ema_200
                cond_bear_tr = close < ema50 and ema20 < ema50
                cond_bear_mc = (prev_macd >= prev_signal) and (macd < signal)
                cond_bear_rsi = (100 - rsi_upper) < rsi < (100 - rsi_lower)

                if cond_btc_s and cond_bear_tr and cond_bear_mc and cond_bear_rsi and volume > vol_sma * vol_sma_multiplier:
                    spend = balance * POSITION_FRACTION
                    entry_fee = spend * FEE_PER_SIDE
                    total_fees += entry_fee
                    notional = spend - entry_fee
                    qty = notional / close
                    balance -= spend
                    entry_price = close
                    highest_price = close
                    lowest_price = close
                    side = "SHORT"
                    atr_dist = atr * atr_multiplier if atr > 0 else close * 0.03
                    dynamic_sl = close + atr_dist
                    entered = True

        # ── HOLDING LONG ─────────────────────────────────────────────────
        elif side == "LONG":
            if high > highest_price:
                highest_price = high

            exit_price = None

            if low <= dynamic_sl:
                exit_price = dynamic_sl

            elif highest_price >= entry_price * (1.0 + trailing_activation_pct):
                trailing_trigger = highest_price * (1.0 - trailing_pullback_pct)
                if low <= trailing_trigger:
                    exit_price = trailing_trigger

            if exit_price is not None:
                gross = qty * exit_price
                exit_fee = gross * FEE_PER_SIDE
                total_fees += exit_fee
                balance += gross - exit_fee
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                total_pnl_pct += pnl_pct
                total_trades += 1
                if pnl_pct > 0:
                    wins += 1
                else:
                    losses += 1
                qty = 0.0; side = ""; entry_price = 0.0; notional = 0.0

        # ── HOLDING SHORT ────────────────────────────────────────────────
        elif side == "SHORT":
            if low < lowest_price:
                lowest_price = low

            exit_price = None

            if high >= dynamic_sl:
                exit_price = dynamic_sl

            elif lowest_price <= entry_price * (1.0 - trailing_activation_pct):
                trailing_trigger = lowest_price * (1.0 + trailing_pullback_pct)
                if high >= trailing_trigger:
                    exit_price = trailing_trigger

            if exit_price is not None:
                gross = qty * (2 * entry_price - exit_price)
                if gross < 0:
                    gross = 0.0
                exit_fee = gross * FEE_PER_SIDE
                total_fees += exit_fee
                balance += gross - exit_fee
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100
                total_pnl_pct += pnl_pct
                total_trades += 1
                if pnl_pct > 0:
                    wins += 1
                else:
                    losses += 1
                qty = 0.0; side = ""; entry_price = 0.0; notional = 0.0

        # ── Equity for Sharpe / Drawdown ─────────────────────────────────
        if qty > 0 and side == "LONG":
            equity = balance + qty * close
        elif qty > 0 and side == "SHORT":
            equity = balance + qty * (2 * entry_price - close)
        else:
            equity = balance

        equity_values.append(equity)

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    # ── Force-close remaining position ───────────────────────────────────
    if qty > 0:
        last_close = closes[-1]
        if side == "LONG":
            gross = qty * last_close
        else:
            gross = qty * (2 * entry_price - last_close)
            if gross < 0:
                gross = 0.0
        exit_fee = gross * FEE_PER_SIDE
        total_fees += exit_fee
        balance += gross - exit_fee
        pnl_pct = ((last_close - entry_price) / entry_price * 100) if side == "LONG" \
            else ((entry_price - last_close) / entry_price * 100)
        total_pnl_pct += pnl_pct
        total_trades += 1
        if pnl_pct > 0:
            wins += 1
        else:
            losses += 1

    # ── Compute Sharpe ───────────────────────────────────────────────────
    sharpe = 0.0
    if len(equity_values) > 10:
        eq_arr = np.array(equity_values)
        returns = np.diff(eq_arr) / eq_arr[:-1]
        returns = returns[np.isfinite(returns)]
        if len(returns) > 0 and np.std(returns) > 0:
            ann_factor = math.sqrt(2190)  # 4h periods per year
            sharpe = (np.mean(returns) / np.std(returns)) * ann_factor

    total_return_pct = (balance - initial_balance) / initial_balance * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "final_balance": round(balance, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 3),
        "total_fees": round(total_fees, 2),
    }


# ---------------------------------------------------------------------------
# 3.  Optuna Objective Function
# ---------------------------------------------------------------------------

# Global in-memory data store (loaded once, reused across all 100 trials)
_DATASETS: dict[str, pd.DataFrame] = {}


def objective(trial: optuna.Trial) -> float:
    """
    Optuna objective — runs the full multi-ticker backtest with the
    trial's suggested parameters and returns a risk-adjusted score.
    """
    # ── Phase 44.3: Zoom-In Precision Search Space ───────────────────────
    # Ranges tightened around best-found region (RSI 38-65, ATR 1.9x, etc.)
    # Finer step sizes for surgical precision
    rsi_lower              = trial.suggest_int("rsi_lower", 34, 44)
    rsi_upper              = trial.suggest_int("rsi_upper", 62, 70)
    atr_multiplier         = trial.suggest_float("atr_multiplier", 1.5, 2.5, step=0.05)
    trailing_activation_pct = trial.suggest_float("trailing_activation_pct", 0.03, 0.08, step=0.002)
    trailing_pullback_pct  = trial.suggest_float("trailing_pullback_pct", 0.003, 0.015, step=0.001)
    vol_sma_multiplier     = trial.suggest_float("vol_sma_multiplier", 0.70, 1.20, step=0.025)
    min_candle_body_pct    = trial.suggest_float("min_candle_body_pct", 0.00, 0.10, step=0.01)

    # ── Run backtest across ALL tickers ──────────────────────────────────
    portfolio_return = 0.0
    portfolio_drawdown = 0.0
    portfolio_trades = 0
    portfolio_wins = 0
    portfolio_sharpe_sum = 0.0

    for ticker, df in _DATASETS.items():
        metrics = run_backtest(
            df=df,
            symbol=ticker,
            rsi_lower=rsi_lower,
            rsi_upper=rsi_upper,
            atr_multiplier=atr_multiplier,
            trailing_activation_pct=trailing_activation_pct,
            trailing_pullback_pct=trailing_pullback_pct,
            vol_sma_multiplier=vol_sma_multiplier,
            min_candle_body_pct=min_candle_body_pct,
            initial_balance=INITIAL_BALANCE,
        )
        portfolio_return += metrics["total_return_pct"]
        portfolio_drawdown = max(portfolio_drawdown, metrics["max_drawdown_pct"])
        portfolio_trades += metrics["total_trades"]
        portfolio_wins += metrics["wins"]
        portfolio_sharpe_sum += metrics["sharpe_ratio"]

    avg_return = portfolio_return / len(_DATASETS)
    avg_sharpe = portfolio_sharpe_sum / len(_DATASETS)
    win_rate = (portfolio_wins / portfolio_trades * 100) if portfolio_trades > 0 else 0

    # ── Enhanced Score: blend of risk-adjusted return + Sharpe ───────────
    if portfolio_drawdown < 0.01:
        portfolio_drawdown = 0.01

    # Core: return / drawdown
    rr_score = avg_return / portfolio_drawdown
    # Sharpe bonus (weighted 20%)
    score = rr_score * 0.8 + max(avg_sharpe, 0) * 0.2

    # Penalise strategies with too few trades
    if portfolio_trades < 15:
        score *= 0.05

    trial.set_user_attr("avg_return_pct", round(avg_return, 2))
    trial.set_user_attr("max_drawdown_pct", round(portfolio_drawdown, 2))
    trial.set_user_attr("total_trades", portfolio_trades)
    trial.set_user_attr("win_rate", round(win_rate, 2))
    trial.set_user_attr("avg_sharpe", round(avg_sharpe, 3))

    return score


# ---------------------------------------------------------------------------
# 4.  Report Printer
# ---------------------------------------------------------------------------

def print_optimization_report(study: optuna.Study) -> None:
    """Print a beautiful ASCII report of the best parameters found."""
    best = study.best_trial

    print()
    print("  " + "=" * 76)
    print(f"  ||" + " PHASE 44.3 — OPTUNA PRECISION REFINEMENT COMPLETE ".center(72) + "||")
    print(f"  ||" + " 7 Params | 1000 Trials | Zoomed Search | CMA-ES ".center(72) + "||")
    print("  " + "=" * 76)

    print(f"\n  +{'─'*74}+")
    print(f"  | {'ABSOLUTE BEST PARAMETERS FOUND':^72} |")
    print(f"  +{'─'*74}+")
    print(f"  |  RSI Lower Bound:            {best.params['rsi_lower']:<42} |")
    print(f"  |  RSI Upper Bound:            {best.params['rsi_upper']:<42} |")
    print(f"  |  ATR Stop-Loss Multiplier:   {best.params['atr_multiplier']:<42.1f} |")
    print(f"  |  Trailing Activation (%):    {best.params['trailing_activation_pct'] * 100:<42.1f} |")
    print(f"  |  Trailing Pullback (%):      {best.params['trailing_pullback_pct'] * 100:<42.1f} |")
    print(f"  |  Volume SMA Multiplier:      {best.params['vol_sma_multiplier']:<42.2f} |")
    print(f"  |  Min Candle Body (%):        {best.params['min_candle_body_pct'] * 100:<42.1f} |")
    print(f"  +{'─'*74}+")

    print(f"\n  +{'─'*74}+")
    print(f"  | {'PERFORMANCE WITH BEST PARAMETERS':^72} |")
    print(f"  +{'─'*74}+")
    avg_ret = best.user_attrs.get("avg_return_pct", 0)
    max_dd  = best.user_attrs.get("max_drawdown_pct", 0)
    trades  = best.user_attrs.get("total_trades", 0)
    wr      = best.user_attrs.get("win_rate", 0)
    sharpe  = best.user_attrs.get("avg_sharpe", 0)
    print(f"  |  Optimization Score:          {best.value:<42.4f} |")
    print(f"  |  Avg Return (per ticker):     {avg_ret:>+10.2f}%{'':31} |")
    print(f"  |  Max Drawdown:                {max_dd:>10.2f}%{'':31} |")
    print(f"  |  Avg Sharpe Ratio:            {sharpe:>10.3f}{'':32} |")
    print(f"  |  Total Trades (all tickers):  {trades:<42} |")
    print(f"  |  Win Rate:                    {wr:>10.2f}%{'':31} |")
    print(f"  +{'─'*74}+")

    # Top-5 trials
    top5 = sorted(study.trials, key=lambda t: t.value if t.value is not None else -1e9, reverse=True)[:5]

    print(f"\n  +{'─'*74}+")
    print(f"  | {'TOP 5 TRIALS':^72} |")
    print(f"  +{'─'*74}+")
    print(f"  |  {'#':<5} {'Score':>8} {'Return':>10} {'MaxDD':>8} {'Trades':>8} {'WinRate':>9} {'RSI':>8} {'ATR':>6}  |")
    print(f"  |  {'─'*70}  |")

    for rank, t in enumerate(top5, 1):
        t_ret = t.user_attrs.get("avg_return_pct", 0)
        t_dd  = t.user_attrs.get("max_drawdown_pct", 0)
        t_tr  = t.user_attrs.get("total_trades", 0)
        t_wr  = t.user_attrs.get("win_rate", 0)
        rsi_str = f"{t.params['rsi_lower']}-{t.params['rsi_upper']}"
        atr_str = f"{t.params['atr_multiplier']:.1f}x"
        score = t.value if t.value is not None else 0
        print(
            f"  |  #{rank:<4} {score:>8.3f} {t_ret:>+9.2f}% {t_dd:>7.2f}% "
            f"{t_tr:>8} {t_wr:>8.2f}% {rsi_str:>8} {atr_str:>6}  |"
        )
    print(f"  +{'─'*74}+")

    # Parameter importance (if enough trials)
    print(f"\n  +{'─'*74}+")
    print(f"  | {'PARAMETER SENSITIVITY':^72} |")
    print(f"  +{'─'*74}+")
    try:
        importances = optuna.importance.get_param_importances(study)
        for param, imp in importances.items():
            bar = "█" * int(imp * 50)
            print(f"  |  {param:<30} {imp:>6.1%}  {bar:<33} |")
    except Exception:
        print(f"  |  {'(Not enough completed trials for importance analysis)':^72} |")
    print(f"  +{'─'*74}+")

    # Config suggestion
    print(f"\n  +{'─'*74}+")
    print(f"  | {'SUGGESTED .env / CONFIG UPDATE':^72} |")
    print(f"  +{'─'*74}+")
    print(f"  |  RSI_LOWER={best.params['rsi_lower']:<63} |")
    print(f"  |  RSI_UPPER={best.params['rsi_upper']:<63} |")
    print(f"  |  ATR_MULTIPLIER={best.params['atr_multiplier']:<56.1f} |")
    print(f"  |  TRAILING_ACTIVATION_PCT={best.params['trailing_activation_pct']:<47.3f} |")
    print(f"  |  TRAILING_PULLBACK_PCT={best.params['trailing_pullback_pct']:<49.3f} |")
    print(f"  |  VOL_SMA_MULTIPLIER={best.params['vol_sma_multiplier']:<52.2f} |")
    print(f"  |  MIN_CANDLE_BODY_PCT={best.params['min_candle_body_pct']:<51.3f} |")
    print(f"  +{'─'*74}+")

    print()
    print("  " + "=" * 76)
    print("  ||" + " OPTIMIZATION COMPLETE — DEPLOY THESE PARAMETERS WITH CONFIDENCE ".center(72) + "||")
    print("  " + "=" * 76)
    print()


# ---------------------------------------------------------------------------
# 5.  Main Entrypoint
# ---------------------------------------------------------------------------

async def load_data() -> None:
    """Downloads / loads all ticker data into the global _DATASETS dict."""
    global _DATASETS

    print()
    print("  " + "=" * 76)
    print("  ||" + " PHASE 44.3 — PRECISION REFINEMENT OPTIMIZATION ".center(72) + "||")
    print("  ||" + " 7 Params | 1000 Trials | CMA-ES | Zoomed Search Space ".center(72) + "||")
    print("  " + "=" * 76)
    print()

    print("  STEP 1: DATA ACQUISITION (cached in memory for speed)")
    print("  " + "-" * 50)

    for ticker in TICKERS:
        _DATASETS[ticker] = await fetch_ticker_data(
            symbol=ticker, timeframe=TIMEFRAME, days=DAYS_BACK,
        )

    # Merge BTC Health Guard
    btc_df = _DATASETS.get("BTC/USDT")
    if btc_df is not None:
        print("\n  [HEALTH GUARD] Merging BTC 200 EMA to all tickers...")
        btc_subset = btc_df[["timestamp", "close", "EMA_200"]].copy()
        btc_subset.rename(
            columns={"close": "BTC_close", "EMA_200": "BTC_EMA_200"}, inplace=True
        )
        for ticker in TICKERS:
            merged = pd.merge(_DATASETS[ticker], btc_subset, on="timestamp", how="left")
            merged.ffill(inplace=True)
            merged.dropna(inplace=True)
            _DATASETS[ticker] = merged

    total_candles = sum(len(df) for df in _DATASETS.values())
    print(f"\n  Data loaded: {total_candles:,} total candles across {len(TICKERS)} tickers")
    print(f"  All data cached in memory — iterations will be FAST\n")


def run_optimization() -> None:
    """Creates Optuna study with a warm-start TPE → CMA-ES sampler and runs 1000 trials."""
    N_TRIALS = 1000

    print("  STEP 2: OPTUNA PRECISION REFINEMENT (Phase 44.3)")
    print("  " + "-" * 50)
    print(f"  Running {N_TRIALS} trials | Zoomed search space | CMA-ES seed=123...\n")

    sampler = optuna.samplers.CmaEsSampler(
        seed=123,
        n_startup_trials=50,
        warn_independent_sampling=False,
        consider_pruned_trials=False,
    )
    study = optuna.create_study(
        direction="maximize",
        study_name="GrokSniper_Phase44_3_PrecisionRefine",
        sampler=sampler,
    )

    t0 = time.time()
    best_score_so_far = -1e9

    def progress_callback(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        nonlocal best_score_so_far
        n = trial.number + 1
        val = trial.value if trial.value is not None else 0

        if val > best_score_so_far:
            best_score_so_far = val
            marker = " ★ NEW BEST"
        else:
            marker = ""

        elapsed = time.time() - t0
        eta = (elapsed / n) * (N_TRIALS - n) if n > 0 else 0

        if n % 5 == 0 or n <= 3 or marker:
            sys.stdout.write(
                f"\r  Trial {n:>3}/{N_TRIALS} | Score: {val:>8.3f} | "
                f"Best: {best_score_so_far:>8.3f} | "
                f"ETA: {eta:.0f}s{marker}          \n"
            )
            sys.stdout.flush()

    study.optimize(objective, n_trials=N_TRIALS, callbacks=[progress_callback])

    total_time = time.time() - t0
    print(f"\n  Optimization completed in {total_time:.0f}s ({total_time/60:.1f} min)")

    # Step 3: Report
    print_optimization_report(study)


async def main() -> None:
    await load_data()
    run_optimization()


if __name__ == "__main__":
    asyncio.run(main())
