"""
Phase 50.1 -- Multi-Timeframe (MTF) Alignment Filter
=====================================================
Prevents the bot from taking trades against the macro trend by checking
the Higher Timeframe (HTF) BEFORE executing any BUY or SELL order.

Timeframe mapping:
  Primary 1h  ->  HTF 4h  (default)
  Primary 4h  ->  HTF 1d
  Primary 15m ->  HTF 1h

Score-based alignment check (2 indicators, need >= threshold to align):
  1. HTF EMA Stack:  EMA20 > EMA50 = +1 (bullish macro)
  2. HTF RSI:        RSI > 50       = +1 (bullish momentum)

  LONG  aligned  >=  1 of 2 signals bullish
  SHORT aligned  >=  1 of 2 signals bearish
  (Both required = ultra-strict, 1+ = permissive institutional standard)

Usage:
  from backend.src.services.mtf_filter import check_htf_alignment, MTFResult

  result = await check_htf_alignment(
      exchange=_exchange,
      ticker="BTC",
      primary_tf="1h",
      direction="LONG",   # or "SHORT"
  )
  if not result.aligned:
      logger.info(result.block_reason)
      continue  # skip this trade
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("groksniper.mtf")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maps primary TF -> Higher TF to check macro trend on
HTF_MAP: dict[str, str] = {
    "1m":  "15m",
    "3m":  "15m",
    "5m":  "1h",
    "15m": "1h",
    "30m": "4h",
    "1h":  "4h",
    "2h":  "4h",
    "4h":  "1d",
    "6h":  "1d",
    "12h": "1d",
    "1d":  "1w",
}

# Minimum bullish (or bearish) signals required from the HTF indicator stack
# to count as "aligned". 1 = permissive, 2 = ultra strict (both must agree)
ALIGNMENT_THRESHOLD = 1   # >=1 out of 2 indicators must confirm direction


# ---------------------------------------------------------------------------
# Result Dataclass
# ---------------------------------------------------------------------------

@dataclass
class MTFResult:
    """Immutable result of an HTF alignment check."""
    aligned:       bool
    htf_timeframe: str
    htf_ema_bull:  bool     # EMA20 > EMA50 on HTF
    htf_rsi_bull:  bool     # RSI > 50 on HTF
    bull_score:    int       # 0-2: how many HTF signals are bullish
    htf_ema20:    float
    htf_ema50:    float
    htf_rsi:      float
    direction:     str       # "LONG" or "SHORT"
    block_reason:  str       # Human-readable message (if blocked)
    tag:           str       # Telegram tag: [HTF: ALIGNED] or [HTF: BLOCKED]


# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def _htf_for(primary_tf: str) -> str:
    """Return the appropriate HTF for a given primary timeframe."""
    return HTF_MAP.get(primary_tf, "4h")   # Default to 4h if unknown


def _classify(
    ema20: float,
    ema50: float,
    rsi: float,
    direction: str,
    htf_tf: str,
) -> MTFResult:
    """
    Pure classification function -- no I/O.
    Scores the HTF indicator stack and returns an MTFResult.
    """
    htf_ema_bull = ema20 > ema50        # EMA stack bullish?
    htf_rsi_bull = rsi > 50.0           # RSI above midpoint?

    bull_score = int(htf_ema_bull) + int(htf_rsi_bull)
    bear_score = (2 - bull_score)

    if direction == "LONG":
        aligned = bull_score >= ALIGNMENT_THRESHOLD
        if aligned:
            reason = (
                f"HTF {htf_tf} aligned LONG: "
                f"EMA20({ema20:.2f}){'>'if htf_ema_bull else '<'}EMA50({ema50:.2f}), "
                f"RSI={rsi:.1f}"
            )
            tag = "[HTF: ALIGNED]"
        else:
            reason = (
                f"Trade Blocked: HTF Macro Trend is Bearish "
                f"[{htf_tf} EMA20({ema20:.2f})<EMA50({ema50:.2f}), "
                f"RSI={rsi:.1f}]"
            )
            tag = "[HTF: BLOCKED]"
    else:   # SHORT
        aligned = bear_score >= ALIGNMENT_THRESHOLD
        if aligned:
            reason = (
                f"HTF {htf_tf} aligned SHORT: "
                f"EMA20({ema20:.2f}){'<'if not htf_ema_bull else '>'}EMA50({ema50:.2f}), "
                f"RSI={rsi:.1f}"
            )
            tag = "[HTF: ALIGNED]"
        else:
            reason = (
                f"Trade Blocked: HTF Macro Trend is Bullish -- no SHORT "
                f"[{htf_tf} EMA20({ema20:.2f})>EMA50({ema50:.2f}), "
                f"RSI={rsi:.1f}]"
            )
            tag = "[HTF: BLOCKED]"

    return MTFResult(
        aligned=aligned,
        htf_timeframe=htf_tf,
        htf_ema_bull=htf_ema_bull,
        htf_rsi_bull=htf_rsi_bull,
        bull_score=bull_score,
        htf_ema20=ema20,
        htf_ema50=ema50,
        htf_rsi=rsi,
        direction=direction,
        block_reason=reason,
        tag=tag,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def check_htf_alignment(
    ticker: str,
    primary_tf: str = "1h",
    direction: str = "LONG",
    exchange=None,
) -> MTFResult:
    """
    Fetch HTF indicators and return an MTFResult.

    Args:
        ticker:      Base ticker, e.g. "BTC", "DOGE"
        primary_tf:  The timeframe the TA signal was generated on
        direction:   "LONG" or "SHORT"
        exchange:    CryptoExchange instance (preferred). If None, uses raw ccxt.

    Returns:
        MTFResult -- check `.aligned` and `.tag` for downstream use.
    """
    htf_tf = _htf_for(primary_tf)

    # Fast path via the existing exchange service
    if exchange is not None:
        try:
            htf_data = await exchange.get_technical_indicators(ticker, htf_tf)
            ema20 = float(htf_data.get("ema_20", 0.0))
            ema50 = float(htf_data.get("ema_50", 0.0))
            rsi   = float(htf_data.get("rsi", 50.0))

            if ema20 > 0 and ema50 > 0:
                result = _classify(ema20, ema50, rsi, direction, htf_tf)
                logger.info(f"[MTF] {ticker} {direction} | {result.tag} | {result.block_reason}")
                return result

        except Exception as e:
            logger.warning(f"[MTF] Exchange path failed for {ticker}: {e}. Trying direct ccxt.")

    # Fallback: direct ccxt fetch (no auth needed for OHLCV)
    return await _fetch_htf_via_ccxt(ticker, htf_tf, direction)


async def _fetch_htf_via_ccxt(
    ticker: str,
    htf_tf: str,
    direction: str,
) -> MTFResult:
    """Raw ccxt fallback when no exchange instance is provided."""
    import ccxt.async_support as ccxt
    import pandas as pd
    import pandas_ta as ta_lib

    symbol = f"{ticker}/USDT" if "/" not in ticker else ticker
    ex = ccxt.binance({"enableRateLimit": True})

    # Default permissive result (fail-open -- don't block on data errors)
    _default = MTFResult(
        aligned=True, htf_timeframe=htf_tf,
        htf_ema_bull=True, htf_rsi_bull=True,
        bull_score=2, htf_ema20=0.0, htf_ema50=0.0, htf_rsi=50.0,
        direction=direction,
        block_reason="MTF data unavailable -- defaulting to ALIGNED (fail-open)",
        tag="[HTF: ALIGNED*]",
    )

    try:
        ohlcv = await ex.fetch_ohlcv(symbol, htf_tf, limit=100)
        if not ohlcv or len(ohlcv) < 55:
            logger.warning(f"[MTF] Not enough HTF candles for {ticker} {htf_tf}")
            return _default

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["close"] = df["close"].astype(float)

        df["ema20"] = ta_lib.ema(df["close"], length=20)
        df["ema50"] = ta_lib.ema(df["close"], length=50)
        df["rsi"]   = ta_lib.rsi(df["close"], length=14)

        df.dropna(inplace=True)
        if df.empty:
            return _default

        row  = df.iloc[-1]
        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        rsi   = float(row["rsi"])

        result = _classify(ema20, ema50, rsi, direction, htf_tf)
        logger.info(f"[MTF ccxt] {ticker} {direction} | {result.tag} | {result.block_reason}")
        return result

    except Exception as e:
        logger.error(f"[MTF] ccxt fetch failed for {ticker}: {e}. Defaulting to ALIGNED.")
        return _default
    finally:
        await ex.close()


# ---------------------------------------------------------------------------
# Standalone Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    async def _test():
        test_cases = [
            ("BTC",  "1h",  "LONG"),
            ("ETH",  "1h",  "LONG"),
            ("DOGE", "1h",  "LONG"),
            ("SOL",  "4h",  "SHORT"),
        ]

        print()
        print("  " + "=" * 70)
        print("  || PHASE 50.1 - MTF ALIGNMENT FILTER - LIVE TEST              ||")
        print("  " + "=" * 70)
        print()
        print(f"  {'Ticker':<8} {'Primary':<8} {'HTF':<5} {'Dir':<6} {'Result':<18} {'EMA20 vs EMA50'}")
        print("  " + "-" * 70)

        for ticker, ptf, direction in test_cases:
            result = await check_htf_alignment(ticker, ptf, direction)
            verdict = "ALIGNED" if result.aligned else "BLOCKED"
            verdict_str = f"[{verdict}]"
            ema_str = f"{result.htf_ema20:,.2f} vs {result.htf_ema50:,.2f} | RSI {result.htf_rsi:.1f}"
            print(f"  {ticker:<8} {ptf:<8} {result.htf_timeframe:<5} {direction:<6} {verdict_str:<18} {ema_str}")

        print()
        print("  Detail for BTC LONG:")
        btc = await check_htf_alignment("BTC", "1h", "LONG")
        print(f"    Tag:    {btc.tag}")
        print(f"    Reason: {btc.block_reason}")
        print(f"    EMA20 > EMA50: {btc.htf_ema_bull} | RSI Bull: {btc.htf_rsi_bull}")
        print()

    asyncio.run(_test())
