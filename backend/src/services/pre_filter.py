"""
pre_filter.py
-------------
Cost-saving pre-filter that checks basic chart structure (ADX, RSI)
before waking expensive LLM agents.  Runs pure Python — no API keys needed.
"""

import logging

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger("groksniper.pre_filter")


async def passes_pre_filter(ticker: str) -> bool:
    """
    Fetch the latest 1h candle data and check ADX / RSI.

    Returns False (reject) when:
      • ADX < 20  → choppy, directionless market
      • 40 < RSI < 60  → neutral zone, no momentum

    On any error the function returns True (fail-open) so the bot
    never silently freezes.
    """
    if ticker in ("NONE", "UNKNOWN", ""):
        return False

    symbol = f"{ticker}/USDT"
    exchange = ccxt.binance({"enableRateLimit": True})

    try:
        # 60 candles ≈ 2.5 days on the 1h timeframe — enough for ADX(14)
        ohlcv = await exchange.fetch_ohlcv(symbol, "1h", limit=60)

        if not ohlcv or len(ohlcv) < 20:
            logger.warning(
                f"[PreFilter] {ticker}: insufficient OHLCV data "
                f"({len(ohlcv) if ohlcv else 0} candles). Passing by default."
            )
            return True

        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        # ── Compute indicators ────────────────────────────────────────────
        df["rsi"] = ta.rsi(df["close"], length=14)
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)

        # pandas_ta.adx returns a DataFrame with columns like ADX_14, DMP_14, DMN_14
        adx_col = [c for c in adx_df.columns if c.startswith("ADX")] if adx_df is not None else []
        adx_value = float(adx_df[adx_col[0]].iloc[-1]) if adx_col and pd.notna(adx_df[adx_col[0]].iloc[-1]) else None
        rsi_value = float(df["rsi"].iloc[-1]) if pd.notna(df["rsi"].iloc[-1]) else None

        # ── Gate logic ────────────────────────────────────────────────────
        if adx_value is not None and adx_value < 20:
            logger.info(
                f"[PreFilter] {ticker}: ADX={adx_value:.1f} < 20. LLM sleep mode."
            )
            return False

        if rsi_value is not None and 40 < rsi_value < 60:
            logger.info(
                f"[PreFilter] {ticker}: RSI={rsi_value:.1f} in neutral zone (40-60). LLM sleep mode."
            )
            return False

        adx_str = f"{adx_value:.1f}" if adx_value is not None else "N/A"
        rsi_str = f"{rsi_value:.1f}" if rsi_value is not None else "N/A"
        logger.info(
            f"[PreFilter] {ticker}: ADX={adx_str}, RSI={rsi_str} — PASSED. Proceeding."
        )
        return True

    except Exception as e:
        logger.warning(f"[PreFilter] {ticker}: error during pre-filter ({e}). Passing by default.")
        return True
    finally:
        await exchange.close()
