"""
shadow_logger.py
-----------------
Phase 51/52 — Order Book Imbalance (OBI) Detector, Volume Delta (Footprint)
& Shadow Statistical Logging.

Silently records every scanner evaluation to a CSV file for off-line statistical
analysis.  No trade decisions are made here — this is pure observation.

Phase 52 adds Volume Delta: Taker Buy Volume minus Taker Sell Volume from
recent executed trades, to detect real buying/selling pressure vs. spoofed
limit orders in the order book.

CSV Path: backend/logs/shadow_statistics.csv
"""

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import ccxt.async_support as ccxt

logger = logging.getLogger("groksniper.shadow")

# ---------------------------------------------------------------------------
# CSV Configuration
# ---------------------------------------------------------------------------
_LOG_DIR  = Path(__file__).resolve().parent.parent.parent / "logs"
_CSV_PATH = _LOG_DIR / "shadow_statistics.csv"

_CSV_COLUMNS = [
    "Timestamp",
    "Ticker",
    "Price",
    "Regime",
    "MTF_Aligned",
    "RSI",
    "EMA_20",
    "EMA_50",
    "MACD_Cross",
    "Volume_Ratio",
    "ATR",
    "Funding_Rate",
    "OBI",
    "Volume_Delta",
    "AI_Sentiment",
    "Action_Signal",
]


# ---------------------------------------------------------------------------
# Order Book Imbalance (OBI) Calculator
# ---------------------------------------------------------------------------
async def calculate_obi(ticker: str, depth: int = 20) -> float:
    """
    Fetch an L2 order book and compute OBI.

        OBI = (V_bids - V_asks) / (V_bids + V_asks)

    Returns a float in [-1.0, 1.0].
      +1.0 = extreme buy pressure  (all bids, no asks)
      -1.0 = extreme sell pressure (all asks, no bids)
       0.0 = perfectly balanced book

    Uses a throwaway public CCXT client (no API keys required).
    """
    symbol = f"{ticker}/USDT" if "/" not in ticker else ticker

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        book = await exchange.fetch_order_book(symbol, limit=depth)
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        # Sum volumes:  each level is [price, qty]
        v_bids = sum(float(level[1]) for level in bids)
        v_asks = sum(float(level[1]) for level in asks)

        total = v_bids + v_asks
        if total == 0:
            return 0.0

        obi = (v_bids - v_asks) / total
        logger.debug(f"[OBI] {symbol} depth={depth} | V_bids={v_bids:.4f} V_asks={v_asks:.4f} → OBI={obi:+.4f}")
        return round(obi, 6)

    except Exception as e:
        logger.warning(f"[OBI] Failed to calculate OBI for {symbol}: {e}")
        return 0.0
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# Volume Delta (Footprint) — Phase 52
# ---------------------------------------------------------------------------
async def calculate_volume_delta(ticker: str, limit: int = 100) -> float:
    """
    Fetch recent executed (taker) trades and compute net Volume Delta.

        Volume Delta = Sum(Taker Buy Volume) - Sum(Taker Sell Volume)

    Positive delta → aggressive buyers dominating (real demand).
    Negative delta → aggressive sellers dominating (real supply).

    This complements OBI: a positive OBI (lots of bids) combined with a
    negative Volume Delta means those bids are likely spoofed — real money
    is selling.

    Uses a throwaway public CCXT client (no API keys required).
    """
    symbol = f"{ticker}/USDT" if "/" not in ticker else ticker

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        trades = await exchange.fetch_trades(symbol, limit=limit)

        buy_volume  = 0.0
        sell_volume = 0.0

        for t in trades:
            amount = float(t.get("amount", 0))
            side   = t.get("side", "").lower()
            if side == "buy":
                buy_volume += amount
            elif side == "sell":
                sell_volume += amount

        delta = buy_volume - sell_volume
        logger.debug(
            f"[VolDelta] {symbol} last {limit} trades | "
            f"BuyVol={buy_volume:.4f} SellVol={sell_volume:.4f} -> Delta={delta:+.4f}"
        )
        return round(delta, 6)

    except Exception as e:
        logger.warning(f"[VolDelta] Failed to calculate volume delta for {symbol}: {e}")
        return 0.0
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# CSV Shadow Logger
# ---------------------------------------------------------------------------
def _ensure_csv_header() -> None:
    """Create the logs directory and write a CSV header if the file doesn't exist yet."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not _CSV_PATH.exists():
        with open(_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(_CSV_COLUMNS)
        logger.info(f"[Shadow] Created CSV at {_CSV_PATH}")


def log_market_state_to_csv(data: dict) -> None:
    """
    Append a single observation row to shadow_statistics.csv.

    Expected keys in `data`:
        Ticker, Price, Regime, MTF_Aligned, RSI, EMA_20, EMA_50,
        MACD_Cross, Volume_Ratio, ATR, Funding_Rate, OBI,
        AI_Sentiment, Action_Signal
    Missing keys default to empty strings.
    """
    _ensure_csv_header()

    row = [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ]
    for col in _CSV_COLUMNS[1:]:  # skip Timestamp (already added)
        row.append(data.get(col, ""))

    try:
        with open(_CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
    except Exception as e:
        logger.error(f"[Shadow] Failed to write CSV row: {e}")


# ---------------------------------------------------------------------------
# Convenience wrapper for the scanner
# ---------------------------------------------------------------------------
async def log_scanner_evaluation(
    *,
    ticker: str,
    price: float,
    regime: str,
    mtf_aligned: bool,
    rsi: float,
    ema_20: float,
    ema_50: float,
    macd_cross: bool,
    volume_ratio: float,
    atr: float,
    funding_rate: float | None,
    obi: float | None,
    volume_delta: float | None = None,
    ai_sentiment: str,
    action_signal: str,
) -> None:
    """
    All-in-one helper: compute OBI & Volume Delta if not provided, then log to CSV.
    Safe to call fire-and-forget — exceptions are caught internally.
    """
    try:
        if obi is None:
            obi = await calculate_obi(ticker)
        if volume_delta is None:
            volume_delta = await calculate_volume_delta(ticker)

        log_market_state_to_csv({
            "Ticker":        ticker,
            "Price":         f"{price:.4f}",
            "Regime":        regime,
            "MTF_Aligned":   str(mtf_aligned),
            "RSI":           f"{rsi:.2f}",
            "EMA_20":        f"{ema_20:.2f}",
            "EMA_50":        f"{ema_50:.2f}",
            "MACD_Cross":    str(macd_cross),
            "Volume_Ratio":  f"{volume_ratio:.4f}",
            "ATR":           f"{atr:.4f}",
            "Funding_Rate":  f"{funding_rate:.6f}" if funding_rate is not None else "N/A",
            "OBI":           f"{obi:+.6f}",
            "Volume_Delta":  f"{volume_delta:+.6f}",
            "AI_Sentiment":  ai_sentiment,
            "Action_Signal": action_signal,
        })
        logger.debug(f"[Shadow] Logged evaluation for {ticker}: signal={action_signal}")
    except Exception as e:
        logger.warning(f"[Shadow] log_scanner_evaluation failed for {ticker}: {e}")


# ---------------------------------------------------------------------------
# Live Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # UTF-8 safety for Windows terminals
    if sys.stdout.encoding != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    TEST_TICKERS = ["BTC", "ETH", "DOGE"]

    async def _test():
        print("\n" + "=" * 65)
        print("  Phase 52 -- OBI + Volume Delta & Shadow Logger Live Test")
        print("=" * 65)

        import ccxt.async_support as ccxt
        import pandas as pd
        import pandas_ta as ta_lib
        
        exchange = ccxt.binance({"enableRateLimit": True})

        for ticker in TEST_TICKERS:
            print(f"\n>> Fetching OBI + Volume Delta & TA for {ticker}/USDT...")
            
            # 1. Fetch live indicators dynamically via CCXT + pandas_ta
            symbol = f"{ticker}/USDT"
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, "1h", limit=100)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["close"] = df["close"].astype(float)
                
                df["rsi"] = ta_lib.rsi(df["close"], length=14)
                df["ema_20"] = ta_lib.ema(df["close"], length=20)
                df["ema_50"] = ta_lib.ema(df["close"], length=50)
                df["volume_sma_20"] = df["volume"].rolling(window=20).mean()
                df["atr"] = ta_lib.atr(df["high"], df["low"], df["close"], length=14)
                macd = ta_lib.macd(df["close"], fast=12, slow=26, signal=9)
                if macd is not None and not macd.empty:
                    df["macd_line"] = macd.iloc[:, 0]
                    df["macd_signal"] = macd.iloc[:, 2]
                else:
                    df["macd_line"] = 0.0
                    df["macd_signal"] = 0.0
                
                # Extract actual live values from the latest row of the Pandas DataFrame
                row = df.iloc[-1]
                price = row["close"]
                rsi = row["rsi"]
                ema_20 = row["ema_20"]
                ema_50 = row["ema_50"]
                vol_ratio = row["volume"] / row["volume_sma_20"] if row.get("volume_sma_20", 0) > 0 else 0.0
                atr = row["atr"]
                macd_cross = row["macd_line"] > row["macd_signal"]
            except Exception as e:
                print(f"Error fetching TA data for {ticker}: {e}")
                continue

            obi   = await calculate_obi(ticker, depth=20)
            vdelta = await calculate_volume_delta(ticker, limit=100)
            print(f"   Price({ticker})        = {price:.2f}")
            print(f"   OBI({ticker})          = {obi:+.6f}")
            print(f"   Volume Delta({ticker}) = {vdelta:+.6f}")
            print(f"   RSI: {rsi:.2f} | EMA20: {ema_20:.2f} | EMA50: {ema_50:.2f}")

            # Spoofing detection hint
            if obi > 0.3 and vdelta < 0:
                print(f"   [!] POSSIBLE SPOOF: bids look strong but sellers dominate")
            elif obi < -0.3 and vdelta > 0:
                print(f"   [!] POSSIBLE SPOOF: asks look strong but buyers dominate")

            # Write a test row to CSV using the live values
            log_market_state_to_csv({
                "Ticker":        ticker,
                "Price":         f"{price:.2f}",
                "Regime":        "BULL",
                "MTF_Aligned":   "True",
                "RSI":           f"{rsi:.2f}",
                "EMA_20":        f"{ema_20:.2f}",
                "EMA_50":        f"{ema_50:.2f}",
                "MACD_Cross":    str(macd_cross),
                "Volume_Ratio":  f"{vol_ratio:.4f}",
                "ATR":           f"{atr:.4f}",
                "Funding_Rate":  "0.000100",
                "OBI":           f"{obi:+.6f}",
                "Volume_Delta":  f"{vdelta:+.6f}",
                "AI_Sentiment":  "neutral",
                "Action_Signal": "HOLD",
            })
            
        await exchange.close()

        print(f"\n>> CSV written to: {_CSV_PATH}")
        print(">> First 5 lines:")
        with open(_CSV_PATH, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                print(f"   {line.rstrip()}")
                if i >= 4:
                    break
        print("=" * 65)

    asyncio.run(_test())
