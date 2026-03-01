"""
tools.py
--------
Custom CrewAI tools that give agents access to the GrokSniper database
and live market data.

Note: CrewAI tools must be synchronous, so we use sync libraries here
(sync SQLAlchemy, sync ccxt) — separate from the async engine used by FastAPI.
"""

import json
import os
import logging

import ccxt
import pandas as pd
import pandas_ta as ta
from crewai.tools import tool
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sync engine (CrewAI tools cannot be async)
# Convert the asyncpg URL to a psycopg2 URL for sync access.
# ---------------------------------------------------------------------------
_async_url = os.getenv("DATABASE_URL", "")
_sync_url = _async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

_sync_engine = create_engine(
    _sync_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

# Import the model — late import to avoid circular dependency issues
from backend.src.db.models import NewsLog  # noqa: E402

# ---------------------------------------------------------------------------
# Binance config (sync) for TA tools
# ---------------------------------------------------------------------------
_BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "True").lower() == "true"


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1 — News (kept for Fundamental agent)
# ═══════════════════════════════════════════════════════════════════════════
@tool("FetchLatestNewsTool")
def fetch_latest_news(ticker: str) -> str:
    """Fetches the latest news articles for a specific crypto ticker from the database.

    Args:
        ticker: The crypto ticker symbol to search for (e.g. 'BTC', 'ETH').

    Returns:
        A minified JSON array of the 5 most recent news articles for the ticker.
        Each element has keys: date (UTC string) and text (article body).
        Returns a JSON error object if no articles are found.
    """
    stmt = (
        select(NewsLog.raw_text, NewsLog.created_at)
        .where(NewsLog.ticker == ticker.upper())
        .order_by(NewsLog.created_at.desc())
        .limit(5)
    )

    with Session(_sync_engine) as session:
        results = session.execute(stmt).all()

    if not results:
        return json.dumps({"error": f"No news found for {ticker}"}, separators=(',', ':'))

    articles = []
    for raw_text, created_at in results:
        date_str = created_at.strftime("%Y-%m-%dT%H:%MZ") if created_at else "N/A"
        articles.append({"date": date_str, "text": raw_text})

    return json.dumps(articles, separators=(',', ':'))


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2 — Deep Multi-Timeframe Chart Data (for Quant Strategist)
# ═══════════════════════════════════════════════════════════════════════════
def _analyze_timeframe(exchange: ccxt.binance, symbol: str, timeframe: str) -> dict:
    """
    Fetch 200 candles for *symbol* on *timeframe* and compute:
      - ADX (trend strength)
      - ATR % (volatility relative to price)
      - EMA 50 / EMA 200 proximity
      - RSI 14
      - MACD crossover state
      - Latest close price
    Returns a dict with all metrics.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    except Exception as exc:
        return {"error": str(exc)}

    if not ohlcv or len(ohlcv) < 50:
        return {"error": "insufficient_data"}

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

    close = float(df["close"].iloc[-1])

    # ── Indicators ────────────────────────────────────────────────────
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["ema_200"] = ta.ema(df["close"], length=200)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    # ADX
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    adx_val = 0.0
    if adx_df is not None and not adx_df.empty:
        adx_col = [c for c in adx_df.columns if "ADX" in c.upper() and "DM" not in c.upper()]
        if adx_col:
            adx_val = float(adx_df[adx_col[0]].iloc[-1]) if pd.notna(adx_df[adx_col[0]].iloc[-1]) else 0.0

    # MACD
    macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
    macd_line = macd_signal = 0.0
    if macd_df is not None and not macd_df.empty:
        macd_line = float(macd_df.iloc[-1, 0]) if pd.notna(macd_df.iloc[-1, 0]) else 0.0
        macd_signal = float(macd_df.iloc[-1, 2]) if pd.notna(macd_df.iloc[-1, 2]) else 0.0

    latest = df.iloc[-1]
    rsi = float(latest["rsi"]) if pd.notna(latest["rsi"]) else 50.0
    ema_50 = float(latest["ema_50"]) if pd.notna(latest["ema_50"]) else close
    ema_200 = float(latest["ema_200"]) if pd.notna(latest["ema_200"]) else close
    atr = float(latest["atr"]) if pd.notna(latest["atr"]) else 0.0
    atr_pct = round((atr / close * 100), 2) if close > 0 else 0.0

    # ── Derived labels ────────────────────────────────────────────────
    if adx_val >= 25:
        trend = "strong"
    elif adx_val >= 20:
        trend = "moderate"
    else:
        trend = "weak"

    if close > ema_50 > ema_200:
        direction = "bullish"
    elif close < ema_50 < ema_200:
        direction = "bearish"
    elif close > ema_50:
        direction = "above_ema50"
    elif close < ema_50:
        direction = "below_ema50"
    else:
        direction = "neutral"

    ema50_dist = round((close - ema_50) / ema_50 * 100, 2) if ema_50 > 0 else 0.0
    ema200_dist = round((close - ema_200) / ema_200 * 100, 2) if ema_200 > 0 else 0.0
    macd_state = "bull_cross" if macd_line > macd_signal else "bear_cross"

    return {
        "close": round(close, 4),
        "rsi": round(rsi, 1),
        "adx": round(adx_val, 1),
        "atr_pct": atr_pct,
        "ema50": round(ema_50, 4),
        "ema200": round(ema_200, 4),
        "ema50_dist": ema50_dist,
        "ema200_dist": ema200_dist,
        "macd": macd_state,
        "trend": trend,
        "dir": direction,
    }


@tool("FetchDeepChartDataTool")
def fetch_deep_chart_data(ticker: str) -> str:
    """Fetches comprehensive multi-timeframe technical analysis data for a crypto ticker.

    Analyzes 15m, 1h, and 4h timeframes from Binance and computes:
    - ADX (Average Directional Index) for trend strength
    - ATR percentage for volatility measurement
    - EMA 50 and EMA 200 proximity and structure
    - RSI 14 momentum
    - MACD crossover state

    Args:
        ticker: The crypto ticker symbol (e.g. 'BTC', 'ETH').

    Returns:
        A minified JSON object with keys: ticker, regime, strategy, tf (timeframe data).
        Each timeframe contains: close, rsi, adx, atr_pct, ema50, ema200,
        ema50_dist (% distance), ema200_dist (% distance), macd, trend, dir.
    """
    symbol = f"{ticker.upper()}/USDT"

    exchange = ccxt.binance({"enableRateLimit": True})
    if _BINANCE_TESTNET:
        exchange.set_sandbox_mode(True)

    try:
        tf_data = {}
        for tf in ["15m", "1h", "4h"]:
            tf_data[tf] = _analyze_timeframe(exchange, symbol, tf)

        # ── Overall Market Regime Assessment ──────────────────────────
        adx_4h = tf_data["4h"].get("adx", 0)
        dir_4h = tf_data["4h"].get("dir", "neutral")
        atr_pct_4h = tf_data["4h"].get("atr_pct", 0)

        if adx_4h >= 25 and "bullish" in dir_4h:
            regime = "STRONG_UPTREND"
        elif adx_4h >= 25 and "bearish" in dir_4h:
            regime = "STRONG_DOWNTREND"
        elif adx_4h >= 20:
            regime = "MODERATE_TREND"
        elif adx_4h < 20 and atr_pct_4h > 3:
            regime = "VOLATILE_CHOP"
        else:
            regime = "RANGE"

        if "UPTREND" in regime or "DOWNTREND" in regime:
            strategy = "Trend Following"
        elif regime == "RANGE":
            strategy = "Mean Reversion"
        elif regime == "VOLATILE_CHOP":
            strategy = "No Trade"
        else:
            strategy = "Breakout Watch"

        result = {
            "ticker": ticker.upper(),
            "regime": regime,
            "strategy": strategy,
            "tf": tf_data,
        }

        logger.info(f"[DeepChartData] {ticker}: regime={regime}, strategy={strategy}")
        return json.dumps(result, separators=(',', ':'))

    except Exception as e:
        logger.error(f"[DeepChartData] Error for {ticker}: {e}")
        return json.dumps({"error": str(e), "ticker": ticker}, separators=(',', ':'))
    finally:
        exchange.close()
