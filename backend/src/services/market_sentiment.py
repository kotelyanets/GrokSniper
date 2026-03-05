"""
market_sentiment.py
--------------------
Phase 50.2 — On-Chain & Open Interest (OI) Analysis Engine.

Provides "X-ray vision" into retail leverage positioning by fetching
Funding Rate and Open Interest from futures markets via CCXT.

Squeeze Protection Logic:
  - EXTREME_GREED  (funding > +0.025%) → High risk of Long Squeeze  (longs get liquidated)
  - EXTREME_FEAR   (funding < -0.025%) → High risk of Short Squeeze (shorts get liquidated)

When a LONG trade is about to fire and the market is in EXTREME_GREED,
the Kelly position size is CUT IN HALF to reduce exposure.
"""

import logging
import asyncio
from typing import Optional

import ccxt.async_support as ccxt

logger = logging.getLogger("groksniper.sentiment")

# ---------------------------------------------------------------------------
# Squeeze Risk Thresholds (% expressed as a fraction, e.g. 0.025% = 0.00025)
# ---------------------------------------------------------------------------
EXTREME_GREED_THRESHOLD = 0.00025   # Funding > +0.025% → Long Squeeze risk
EXTREME_FEAR_THRESHOLD  = -0.00025  # Funding < -0.025% → Short Squeeze risk

# Risk flag constants
FLAG_LONG_SQUEEZE  = "WARNING: LONG SQUEEZE RISK"
FLAG_SHORT_SQUEEZE = "WARNING: SHORT SQUEEZE RISK"
FLAG_SAFE          = "SAFE"

# ---------------------------------------------------------------------------
# Futures symbol formatter
# ---------------------------------------------------------------------------
def _to_futures_symbol(ticker: str) -> str:
    """Convert a spot ticker (e.g. 'BTC') to a Binance futures symbol ('BTC/USDT:USDT')."""
    base = ticker.replace("/USDT", "").replace("USDT", "").strip().upper()
    return f"{base}/USDT:USDT"


# ---------------------------------------------------------------------------
# Core data fetcher
# ---------------------------------------------------------------------------
async def get_futures_sentiment(ticker: str) -> dict:
    """
    Fetch the current Funding Rate and Open Interest for a given ticker
    from Binance futures (using CCXT async swap mode).

    Returns a dict:
    {
        "ticker": str,
        "futures_symbol": str,
        "funding_rate": float | None,   # e.g. 0.0001 = 0.01%
        "funding_rate_pct": str,        # human-readable "0.0100%"
        "open_interest": float | None,  # in USDT
        "squeeze_flag": str,            # FLAG_SAFE | FLAG_LONG_SQUEEZE | FLAG_SHORT_SQUEEZE
        "error": str | None,
    }
    """
    futures_symbol = _to_futures_symbol(ticker)
    result = {
        "ticker": ticker,
        "futures_symbol": futures_symbol,
        "funding_rate": None,
        "funding_rate_pct": "N/A",
        "open_interest": None,
        "squeeze_flag": FLAG_SAFE,
        "error": None,
    }

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })

    try:
        # Fetch Funding Rate
        try:
            fr_data = await exchange.fetch_funding_rate(futures_symbol)
            funding_rate = fr_data.get("fundingRate") or fr_data.get("fundingRate", None)
            if funding_rate is not None:
                result["funding_rate"] = float(funding_rate)
                result["funding_rate_pct"] = f"{float(funding_rate) * 100:.4f}%"
        except Exception as e:
            logger.warning(f"[Sentiment] Funding rate fetch failed for {futures_symbol}: {e}")

        # Fetch Open Interest
        try:
            oi_data = await exchange.fetch_open_interest(futures_symbol)
            # CCXT returns openInterestValue (in quote currency, USDT) or openInterest (in base)
            oi_value = oi_data.get("openInterestValue") or oi_data.get("openInterest")
            if oi_value is not None:
                result["open_interest"] = float(oi_value)
        except Exception as e:
            logger.warning(f"[Sentiment] Open interest fetch failed for {futures_symbol}: {e}")

        # Evaluate squeeze risk
        if result["funding_rate"] is not None:
            result["squeeze_flag"] = evaluate_squeeze_risk("LONG", result["funding_rate"])

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[Sentiment] Critical error fetching futures data for {ticker}: {e}")
    finally:
        await exchange.close()

    logger.info(
        f"[Sentiment] {ticker} | Funding={result['funding_rate_pct']} "
        f"OI={result['open_interest']} | {result['squeeze_flag']}"
    )
    return result


# ---------------------------------------------------------------------------
# Squeeze Risk Evaluator
# ---------------------------------------------------------------------------
def evaluate_squeeze_risk(direction: str, funding_rate: float) -> str:
    """
    Evaluate whether current funding rate poses a squeeze risk for the trade direction.

    Args:
        direction:    'LONG' or 'SHORT'
        funding_rate: current funding rate as a decimal (e.g. 0.0003 = 0.03%)

    Returns:
        FLAG_LONG_SQUEEZE  → "WARNING: LONG SQUEEZE RISK"
        FLAG_SHORT_SQUEEZE → "WARNING: SHORT SQUEEZE RISK"
        FLAG_SAFE          → "SAFE"
    """
    if direction == "LONG":
        if funding_rate > EXTREME_GREED_THRESHOLD:
            return FLAG_LONG_SQUEEZE
        # Extreme fear (very negative funding) is actually GOOD for longs — shorts get squeezed
        return FLAG_SAFE

    elif direction == "SHORT":
        if funding_rate < EXTREME_FEAR_THRESHOLD:
            return FLAG_SHORT_SQUEEZE
        return FLAG_SAFE

    return FLAG_SAFE


# ---------------------------------------------------------------------------
# Telegram tag builder (injected into send_entry_alert ai_reasoning)
# ---------------------------------------------------------------------------
def build_sentiment_tag(sentiment: dict) -> str:
    """
    Build a compact Telegram tag string to embed in trade alerts.

    Examples:
        "[🌡️ Funding: 0.0300% | ⚠️ SQUEEZE RISK - Size Reduced]"
        "[🌡️ Funding: 0.0100% | ✅ SAFE]"
    """
    fr_pct = sentiment.get("funding_rate_pct", "N/A")
    flag = sentiment.get("squeeze_flag", FLAG_SAFE)

    if flag != FLAG_SAFE:
        return f"[🌡️ Funding: {fr_pct} | ⚠️ SQUEEZE RISK - Size Reduced]"
    else:
        return f"[🌡️ Funding: {fr_pct} | ✅ SAFE]"


# ---------------------------------------------------------------------------
# Live Test — run directly: python -m backend.src.services.market_sentiment
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    import sys

    # Ensure UTF-8 output on Windows (cp1251 terminals drop non-ASCII emoji)
    if sys.stdout.encoding != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    TEST_TICKERS = ["BTC", "ETH", "DOGE"]

    async def _live_test():
        print("\n" + "=" * 65)
        print("  Phase 50.2 -- Sentiment / Squeeze Protection Live Test")
        print("=" * 65)

        for ticker in TEST_TICKERS:
            print(f"\n>>  Fetching futures data for {ticker}...")
            result = await get_futures_sentiment(ticker)

            funding = result["funding_rate"]
            oi      = result["open_interest"]
            flag    = result["squeeze_flag"]
            fr_pct  = result["funding_rate_pct"]
            err     = result["error"]

            print(f"   Symbol       : {result['futures_symbol']}")
            print(f"   Funding Rate : {fr_pct}  ({funding})")
            print(f"   Open Interest: {oi:,.0f} USDT" if oi else "   Open Interest: N/A")
            print(f"   Risk Flag    : {flag}")
            if err:
                print(f"   [!] Error    : {err}")

            # Also test evaluate_squeeze_risk for both directions
            long_flag  = evaluate_squeeze_risk("LONG",  funding or 0.0)
            short_flag = evaluate_squeeze_risk("SHORT", funding or 0.0)
            print(f"   LONG risk    : {long_flag}")
            print(f"   SHORT risk   : {short_flag}")
            print(f"   Telegram tag : {build_sentiment_tag(result)}")
            print("-" * 65)

    asyncio.run(_live_test())
