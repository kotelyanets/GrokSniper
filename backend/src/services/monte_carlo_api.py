import logging
import time
from pathlib import Path
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Путь к stress_test_trades.csv
TRADES_CSV = Path(__file__).resolve().parent.parent / "scripts" / "stress_test_trades.csv"

def run_monte_carlo_web(
    n_simulations: int = 10000,
    trades_per_sim: int = 200,
    initial_balance: float = 10000.0,
    ruin_threshold: float = 0.50
) -> dict:
    """
    Веб-адаптированная версия движка Монте-Карло.
    Использует numpy для быстрых симуляций без отрисовки графиков и rich.
    """
    if not TRADES_CSV.exists():
        logger.error(f"stress_test_trades.csv not found at {TRADES_CSV}")
        raise FileNotFoundError(
            "Stress test trades log not found. Please run a 3-Year Stress Test first to generate trade logs."
        )

    # 1. Загрузка распределения PnL с обработкой пустого файла
    try:
        df = pd.read_csv(TRADES_CSV)
    except pd.errors.EmptyDataError:
        raise ValueError(
            "Stress test trades log is empty. Please run a longer 3-Year Stress Test first to accumulate trade logs."
        )

    if df.empty or "action" not in df.columns or "pnl_pct" not in df.columns:
        raise ValueError(
            "No valid trade columns found. Please run a longer 3-Year Stress Test first to generate trade logs."
        )

    exit_rows = df[df["action"] == "EXIT"].copy()
    if exit_rows.empty:
        raise ValueError(
            "No historical exit trades found in the trade log. Please run a longer 3-Year Stress Test first to accumulate trades."
        )

    pnl_array = exit_rows["pnl_pct"].dropna().values.astype(float)

    if len(pnl_array) == 0:
        raise ValueError(
            "No valid exit PnL percentage values found to simulate. Please run a longer 3-Year Stress Test first."
        )

    n_trades = len(pnl_array)
    mean_pnl = float(pnl_array.mean())
    std_pnl = float(pnl_array.std())
    min_pnl = float(pnl_array.min())
    max_pnl = float(pnl_array.max())
    win_rate = float((np.sum(pnl_array > 0) / n_trades) * 100) if n_trades > 0 else 0.0

    # 2. Симуляция Монте-Карло
    rng = np.random.default_rng(seed=42)
    all_curves = np.zeros((n_simulations, trades_per_sim + 1))
    max_drawdowns = np.zeros(n_simulations)

    all_curves[:, 0] = initial_balance

    t0 = time.time()
    for sim in range(n_simulations):
        sampled_pnl = rng.choice(pnl_array, size=trades_per_sim, replace=True)
        returns = 1.0 + sampled_pnl / 100.0
        equity = initial_balance * np.cumprod(returns)
        all_curves[sim, 1:] = equity

        # Расчет максимальной просадки
        running_peak = np.maximum.accumulate(equity)
        # Избегаем деления на ноль
        running_peak = np.where(running_peak <= 0, 1e-9, running_peak)
        drawdowns = (running_peak - equity) / running_peak * 100
        max_drawdowns[sim] = drawdowns.max()

    elapsed = time.time() - t0
    logger.info(f"Monte Carlo simulation of {n_simulations} paths completed in {elapsed:.2f}s")

    final_balances = all_curves[:, -1]

    # 3. Расчет метрик
    p5, p25, p50, p75, p95 = np.percentile(final_balances, [5, 25, 50, 75, 95])
    mean_balance = float(final_balances.mean())
    std_balance = float(final_balances.std())

    dd_mean = float(max_drawdowns.mean())
    dd_95 = float(np.percentile(max_drawdowns, 95))
    dd_max = float(max_drawdowns.max())

    ruin_count = int(np.sum(max_drawdowns >= ruin_threshold * 100))
    risk_of_ruin = float((ruin_count / n_simulations) * 100)

    profitable = np.sum(final_balances > initial_balance)
    prob_profit = float((profitable / n_simulations) * 100)

    median_return = float((p50 / initial_balance - 1) * 100)

    # 4. Выборка 200 случайных путей для spaghetti-графика
    sample_size = min(200, n_simulations)
    sample_indices = rng.choice(n_simulations, size=sample_size, replace=False)
    sample_curves = []
    for idx in sample_indices:
        sample_curves.append(all_curves[idx].tolist())

    # 5. Генерация гистограммы распределения финального баланса
    counts, bin_edges = np.histogram(final_balances, bins=20)
    histogram = []
    for i in range(len(counts)):
        bucket_label = f"${bin_edges[i]:,.0f} - ${bin_edges[i+1]:,.0f}"
        histogram.append({
            "bucket": bucket_label,
            "count": int(counts[i]),
            "lower_edge": float(bin_edges[i]),
            "upper_edge": float(bin_edges[i+1])
        })

    verdict = "CLEARED" if risk_of_ruin < 1.0 else "NOT_CLEARED"

    return {
        "metrics": {
            "n_simulations": n_simulations,
            "trades_per_sim": trades_per_sim,
            "mean_balance": round(mean_balance, 2),
            "std_balance": round(std_balance, 2),
            "p5_balance": round(float(p5), 2),
            "p25_balance": round(float(p25), 2),
            "median_balance": round(float(p50), 2),
            "p75_balance": round(float(p75), 2),
            "p95_balance": round(float(p95), 2),
            "dd_mean": round(dd_mean, 2),
            "dd_95": round(dd_95, 2),
            "dd_max": round(dd_max, 2),
            "ruin_count": ruin_count,
            "risk_of_ruin": round(risk_of_ruin, 2),
            "prob_profit": round(prob_profit, 2),
            "median_return": round(median_return, 2),
        },
        "input_distribution": {
            "n_trades": n_trades,
            "mean_pnl": round(mean_pnl, 3),
            "std_pnl": round(std_pnl, 3),
            "min_pnl": round(min_pnl, 2),
            "max_pnl": round(max_pnl, 2),
            "win_rate": round(win_rate, 2),
        },
        "sample_curves": sample_curves,
        "histogram": histogram,
        "verdict": verdict,
    }
