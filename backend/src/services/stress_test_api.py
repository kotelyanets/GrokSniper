import logging
import asyncio
import pandas as pd
import numpy as np
import math
from pathlib import Path

# Импортируем оригинальные функции для 100% совместимости
from backend.src.scripts.stress_test import (
    fetch_ticker_data,
    run_stress_test,
    save_csvs
)

logger = logging.getLogger(__name__)

def clean_floats(obj):
    """
    Recursively replaces NaN, inf, and -inf float values in dicts/lists with 0.0
    so that the object is fully JSON-compliant.
    """
    if isinstance(obj, dict):
        return {k: clean_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_floats(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj

async def run_stress_test_web(
    tickers: list = None,
    days_back: int = 1095,
    initial_balance: float = 10000.0
) -> dict:
    """
    Веб-адаптированная версия 3-летнего стресс-теста.
    Запускает оригинальный движок, вычисляет портфельные показатели,
    субсемплирует кривые эквити для быстрого рендеринга и сохраняет CSV.
    """
    if tickers is None:
        tickers = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

    logger.info(f"Starting Stress Test API: tickers={tickers}, days={days_back}, balance={initial_balance}")

    # Шаг 1: Скачивание/загрузка данных для каждого тикера
    datasets = {}
    for ticker in tickers:
        datasets[ticker] = await fetch_ticker_data(
            symbol=ticker,
            timeframe="4h",
            days=days_back
        )

    # Шаг 1b: BTC Health Guard (слияние данных BTC 200 EMA)
    # Если BTC/USDT нет в списке запрошенных тикеров, но нам нужно его поведение, скачаем его отдельно
    if "BTC/USDT" not in datasets:
        logger.info("Downloading BTC/USDT for Health Guard support...")
        btc_df = await fetch_ticker_data(
            symbol="BTC/USDT",
            timeframe="4h",
            days=days_back
        )
    else:
        btc_df = datasets["BTC/USDT"]

    if btc_df is not None and not btc_df.empty:
        logger.info("Merging BTC 200 EMA to all tickers for BTC Health Guard...")
        btc_subset = btc_df[["timestamp", "close", "EMA_200"]].copy()
        btc_subset.rename(columns={"close": "BTC_close", "EMA_200": "BTC_EMA_200"}, inplace=True)
        for ticker in tickers:
            df_ticker = datasets[ticker]
            if df_ticker is not None and not df_ticker.empty:
                # Merge
                merged = pd.merge(df_ticker, btc_subset, on="timestamp", how="left")
                merged.ffill(inplace=True)
                merged.dropna(inplace=True)
                datasets[ticker] = merged

    # Шаг 2: Симуляция
    results = []
    for ticker in tickers:
        df_ticker = datasets[ticker]
        if df_ticker is not None and not df_ticker.empty:
            # run_stress_test синхронная, запустим ее в треде чтобы не блокировать event loop
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                run_stress_test,
                df_ticker,
                ticker,
                initial_balance
            )
            results.append(res)

    if not results:
        raise ValueError("Failed to simulate any ticker data.")

    # Шаг 3: Сохранение CSV (также делает стресс-тест доступным для Monte Carlo)
    try:
        save_csvs(results)
    except Exception as e:
        logger.error(f"Error saving stress test CSVs: {e}")

    # Шаг 4: Форматирование данных для JSON
    per_ticker = []
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_fees = 0.0
    total_initial = 0.0
    total_final = 0.0
    exit_reasons_total = {}

    for r in results:
        symbol = r["symbol"]
        initial = r["initial_balance"]
        final = r["final_balance"]
        
        total_trades += r["total_trades"]
        total_wins += r["wins"]
        total_losses += r["losses"]
        total_fees += r["total_fees_paid"]
        total_initial += initial
        total_final += final

        # Объединение причин выхода
        for reason, count in r["exit_reasons"].items():
            exit_reasons_total[reason] = exit_reasons_total.get(reason, 0) + count

        # Субсемплирование кривой эквити до 500 точек
        eq_curve = r["equity_curve"]
        n_points = len(eq_curve)
        if n_points > 500:
            step = n_points // 500
            sampled_eq = eq_curve[::step]
        else:
            sampled_eq = eq_curve

        # Фильтрация сделок (только EXIT)
        exit_trades = [
            {
                "side": t["side"],
                "timestamp": t["timestamp"],
                "price": t["price"],
                "entry_price": t.get("entry_price", t["price"]),
                "pnl_pct": t.get("pnl_pct", 0.0),
                "pnl_usd": t.get("pnl_usd", 0.0),
                "reason": t.get("reason", "unknown")
            }
            for t in r["trades"] if t["action"] == "EXIT"
        ]

        per_ticker.append({
            "symbol": symbol,
            "initial_balance": initial,
            "final_balance": final,
            "total_return_pct": r["total_return_pct"],
            "total_trades": r["total_trades"],
            "long_trades": r["long_trades"],
            "short_trades": r["short_trades"],
            "wins": r["wins"],
            "losses": r["losses"],
            "win_rate": r["win_rate"],
            "avg_win_pct": r["avg_win_pct"],
            "avg_loss_pct": r["avg_loss_pct"],
            "best_trade_pct": r["best_trade_pct"],
            "worst_trade_pct": r["worst_trade_pct"],
            "expectancy_pct": r["expectancy_pct"],
            "profit_factor": r["profit_factor"],
            "max_drawdown_pct": r["max_drawdown_pct"],
            "sharpe_ratio": r["sharpe_ratio"],
            "sortino_ratio": r["sortino_ratio"],
            "calmar_ratio": r["calmar_ratio"],
            "longest_win_streak": r["longest_win_streak"],
            "longest_loss_streak": r["longest_loss_streak"],
            "total_fees_paid": r["total_fees_paid"],
            "exit_reasons": r["exit_reasons"],
            "equity_curve": sampled_eq,
            "trades": exit_trades,
            "monthly_returns": r["monthly_returns"]
        })

    # Портфельный расчет
    pnl = total_final - total_initial
    pnl_pct = (pnl / total_initial) * 100 if total_initial > 0 else 0.0
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
    
    avg_drawdown = sum(r["max_drawdown_pct"] for r in results) / len(results)
    avg_sharpe = sum(r["sharpe_ratio"] for r in results) / len(results)
    avg_sortino = sum(r["sortino_ratio"] for r in results) / len(results)

    best_ticker = max(results, key=lambda x: x["total_return_pct"])["symbol"]
    worst_ticker = min(results, key=lambda x: x["total_return_pct"])["symbol"]

    portfolio_summary = {
        "total_initial": round(total_initial, 2),
        "total_final": round(total_final, 2),
        "pnl_usd": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": round(win_rate, 2),
        "total_fees": round(total_fees, 2),
        "avg_drawdown_pct": round(avg_drawdown, 2),
        "avg_sharpe": round(avg_sharpe, 3),
        "avg_sortino": round(avg_sortino, 3),
        "best_ticker": best_ticker,
        "worst_ticker": worst_ticker
    }

    raw_response = {
        "per_ticker": per_ticker,
        "portfolio_summary": portfolio_summary,
        "exit_reasons_total": exit_reasons_total
    }
    return clean_floats(raw_response)
