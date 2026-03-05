"""
Phase 48 — Market Regime Detection Engine
==========================================
Classifies the current market environment into one of three regimes:

  BULL  — BTC in uptrend, low chop, strong momentum
          → Use AGGRESSIVE Pareto strategy params (RSI 34-62, ATR 2.1x)

  BEAR  — BTC in downtrend, momentum bearish
          → Use CONSERVATIVE Pareto params (RSI 40-58, ATR 2.0x, strict body/vol)

  CHOP  — Sideways market, low ADX, high ATR-range ratio
          → Skip trades entirely / use ultra-strict filters

Detection logic (multi-factor scoring):
  1. BTC Trend:    close vs EMA200, EMA50, EMA20 (strong directional signals)
  2. ADX:          < 20 → choppy, > 30 → trending
  3. Volatility:   ATR% of price (high chop = large ATR%)
  4. RSI Momentum: >55 bullish, <45 bearish, 45-55 neutral/chop
  5. MACD:         histogram direction (confirms momentum)

Usage:
  from backend.src.services.regime_detector import get_regime, REGIME_PARAMS

  regime, confidence, params = await get_regime(ticker="BTC")
  # regime ∈ {"BULL", "BEAR", "CHOP"}
  # confidence ∈ [0.0, 1.0]
  # params: dict of RSI, ATR, trail, vol, body values to use
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger("groksniper.regime")

# ---------------------------------------------------------------------------
# Regime-Specific Parameter Sets
# Derived from Phase 46 Pareto Optimization results
# ---------------------------------------------------------------------------

REGIME_PARAMS: dict[str, dict] = {
    "BULL": {
        # AGGRESSIVE Pareto profile — ride the trend hard
        "rsi_lower":              34,
        "rsi_upper":              62,
        "atr_multiplier":         2.1,
        "trailing_activation_pct": 0.10,   # 10%
        "trailing_pullback_pct":  0.002,   # 0.2%
        "vol_sma_multiplier":     0.85,
        "min_candle_body_pct":    0.03,
        "label": "BULL (Aggressive)",
    },
    "BEAR": {
        # CONSERVATIVE Pareto profile — preserve capital
        "rsi_lower":              40,
        "rsi_upper":              58,
        "atr_multiplier":         2.0,
        "trailing_activation_pct": 0.02,   # 2%
        "trailing_pullback_pct":  0.003,   # 0.3%
        "vol_sma_multiplier":     1.30,
        "min_candle_body_pct":    0.08,
        "label": "BEAR (Conservative)",
    },
    "CHOP": {
        # BALANCED Pareto profile, trading heavily restricted
        "rsi_lower":              46,
        "rsi_upper":              60,
        "atr_multiplier":         1.6,
        "trailing_activation_pct": 0.095,  # 9.5%
        "trailing_pullback_pct":  0.003,   # 0.3%
        "vol_sma_multiplier":     1.50,    # Extra strict volume gate
        "min_candle_body_pct":    0.05,
        "label": "CHOP (Sideways - Strict)",
    },
}


# ---------------------------------------------------------------------------
# Regime Score Model
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    regime:     str    # "BULL" | "BEAR" | "CHOP"
    confidence: float  # 0.0 – 1.0
    params:     dict
    bull_score: float
    bear_score: float
    chop_score: float
    details:    str    # Human-readable explanation


def _score_regime(
    close: float,
    ema20: float,
    ema50: float,
    ema200: float,
    rsi: float,
    adx: float,
    atr_pct: float,  # ATR / close
    macd_hist: float,
) -> RegimeResult:
    """
    Pure-function regime scorer.
    Uses a weighted multi-factor scoring approach.
    Returns a RegimeResult with all scores.
    """
    bull_score = 0.0
    bear_score = 0.0
    chop_score = 0.0
    reasons: list[str] = []

    # ── 1. BTC Trend (weight: 35%) ────────────────────────────────────────
    if close > ema200:
        bull_score += 2.0
        reasons.append(f"BULL: close({close:.0f}) > EMA200({ema200:.0f})")
    else:
        bear_score += 2.0
        reasons.append(f"BEAR: close({close:.0f}) < EMA200({ema200:.0f})")

    if ema20 > ema50 and ema50 > ema200:
        bull_score += 1.5
        reasons.append("BULL: EMA20 > EMA50 > EMA200 (strong uptrend)")
    elif ema20 < ema50 and ema50 < ema200:
        bear_score += 1.5
        reasons.append("BEAR: EMA20 < EMA50 < EMA200 (strong downtrend)")
    else:
        chop_score += 0.5
        reasons.append("CHOP: EMA alignment mixed")

    # ── 2. ADX — Trend Strength (weight: 25%) ─────────────────────────────
    if adx > 30:
        # Strong trend — amplify whichever direction dominates so far
        if bull_score > bear_score:
            bull_score += 1.5
            reasons.append(f"BULL: ADX={adx:.1f} (strong trend)")
        else:
            bear_score += 1.5
            reasons.append(f"BEAR: ADX={adx:.1f} (strong trend)")
    elif adx < 20:
        # Weak trend — choppy market
        chop_score += 2.0
        reasons.append(f"CHOP: ADX={adx:.1f} (weak/no trend)")
    else:
        # 20-30: moderate trend
        chop_score += 0.5
        reasons.append(f"NEUTRAL: ADX={adx:.1f} (moderate trend)")

    # ── 3. RSI Momentum (weight: 20%) ─────────────────────────────────────
    if rsi > 55:
        bull_score += 1.0
        reasons.append(f"BULL: RSI={rsi:.1f} (bullish momentum)")
    elif rsi < 45:
        bear_score += 1.0
        reasons.append(f"BEAR: RSI={rsi:.1f} (bearish momentum)")
    else:
        chop_score += 1.0
        reasons.append(f"CHOP: RSI={rsi:.1f} (neutral momentum)")

    # ── 4. MACD Histogram direction (weight: 10%) ─────────────────────────
    if macd_hist > 0:
        bull_score += 0.5
        reasons.append(f"BULL: MACD hist={macd_hist:.4f} > 0")
    elif macd_hist < 0:
        bear_score += 0.5
        reasons.append(f"BEAR: MACD hist={macd_hist:.4f} < 0")

    # ── 5. ATR Volatility (weight: 10%) ───────────────────────────────────
    if atr_pct > 0.05:
        # Extreme volatility → often CHOP or regime transition
        chop_score += 1.0
        reasons.append(f"CHOP: High ATR ({atr_pct*100:.1f}% of price)")
    elif atr_pct < 0.015:
        # Very low volatility → trending calmly
        if bull_score > bear_score:
            bull_score += 0.5
        else:
            bear_score += 0.5
        reasons.append(f"TREND: Low ATR ({atr_pct*100:.1f}% of price)")

    # ── Determine regime ───────────────────────────────────────────────────
    total = bull_score + bear_score + chop_score + 1e-9
    if chop_score >= bull_score and chop_score >= bear_score:
        regime = "CHOP"
        confidence = chop_score / total
    elif bull_score >= bear_score:
        regime = "BULL"
        confidence = bull_score / total
    else:
        regime = "BEAR"
        confidence = bear_score / total

    confidence = round(min(confidence, 1.0), 3)
    detail = " | ".join(reasons)

    return RegimeResult(
        regime=regime,
        confidence=confidence,
        params=REGIME_PARAMS[regime],
        bull_score=round(bull_score, 2),
        bear_score=round(bear_score, 2),
        chop_score=round(chop_score, 2),
        details=detail,
    )


# ---------------------------------------------------------------------------
# Public API — async (calls the exchange for live data)
# ---------------------------------------------------------------------------

async def get_regime(exchange=None, ticker: str = "BTC") -> RegimeResult:
    """
    Fetch live BTC indicators and return a RegimeResult.

    Args:
        exchange: CryptoExchange instance (passed in to avoid circular imports).
                  If None, uses a lightweight ccxt fetch instead.
        ticker:   Ticker to check (default BTC — the macro regime anchor).

    Returns:
        RegimeResult with regime, confidence, and adaptive params.
    """

    if exchange is not None:
        # Use the live exchange service (preferred, already authenticated)
        try:
            ta_4h = await exchange.get_technical_indicators("BTC", "4h")
            ta_1d = await exchange.get_technical_indicators("BTC", "1d")

            close  = ta_4h.get("close",     0.0)
            ema20  = ta_4h.get("ema_20",    close)
            ema50  = ta_4h.get("ema_50",    close)
            ema200 = ta_4h.get("ema_200",   close) or ta_1d.get("ema_200", close)
            rsi    = ta_4h.get("rsi",       50.0)
            atr    = ta_4h.get("atr",       close * 0.02)
            adx    = ta_4h.get("adx",       25.0)    # Falls back to neutral if missing
            macd_l = ta_4h.get("macd_line", 0.0)
            macd_s = ta_4h.get("macd_signal", 0.0)
            macd_hist = macd_l - macd_s
            atr_pct = atr / close if close > 0 else 0.02

            result = _score_regime(
                close=close, ema20=ema20, ema50=ema50, ema200=ema200,
                rsi=rsi, adx=adx, atr_pct=atr_pct, macd_hist=macd_hist,
            )
            logger.info(
                f"[Regime] {result.regime} (conf={result.confidence:.0%}) | "
                f"Bull={result.bull_score} Bear={result.bear_score} Chop={result.chop_score}"
            )
            return result

        except Exception as e:
            logger.warning(f"[Regime] Exchange fetch failed: {e}. Falling back to ccxt.")

    # Lightweight fallback: direct ccxt fetch
    import asyncio
    import ccxt.async_support as ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    try:
        candles = await ex.fetch_ohlcv("BTC/USDT", "4h", limit=250)
        if not candles or len(candles) < 50:
            logger.warning("[Regime] Not enough candles — defaulting to CHOP/BALANCED")
            return RegimeResult(
                regime="CHOP", confidence=0.5,
                params=REGIME_PARAMS["CHOP"],
                bull_score=0, bear_score=0, chop_score=1,
                details="Insufficient data — defaulting to CHOP"
            )

        import pandas as pd
        import pandas_ta as ta_lib

        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)

        df.ta.ema(length=20,  append=True)
        df.ta.ema(length=50,  append=True)
        df.ta.ema(length=200, append=True)
        df.ta.rsi(length=14,  append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.atr(length=14,  append=True)
        df.ta.adx(length=14,  append=True)

        df.dropna(inplace=True)
        if df.empty:
            return RegimeResult(
                regime="CHOP", confidence=0.5, params=REGIME_PARAMS["CHOP"],
                bull_score=0, bear_score=0, chop_score=1,
                details="Empty df after dropna — defaulting to CHOP"
            )

        row = df.iloc[-1]
        close    = float(row["close"])
        ema20    = float(row.get("EMA_20",  close))
        ema50    = float(row.get("EMA_50",  close))
        ema200   = float(row.get("EMA_200", close))
        rsi      = float(row.get("RSI_14",  50.0))
        atr      = float(row.get("ATRr_14", close * 0.02))
        adx      = float(row.get("ADX_14",  25.0))
        macd_l   = float(row.get("MACD_12_26_9",  0.0))
        macd_s   = float(row.get("MACDs_12_26_9", 0.0))
        macd_hist = macd_l - macd_s
        atr_pct  = atr / close if close > 0 else 0.02

        result = _score_regime(
            close=close, ema20=ema20, ema50=ema50, ema200=ema200,
            rsi=rsi, adx=adx, atr_pct=atr_pct, macd_hist=macd_hist,
        )
        logger.info(
            f"[Regime] {result.regime} (conf={result.confidence:.0%}) | "
            f"Bull={result.bull_score} Bear={result.bear_score} Chop={result.chop_score}"
        )
        return result

    finally:
        await ex.close()


# ---------------------------------------------------------------------------
# Utility: should_trade()
# ---------------------------------------------------------------------------

def should_trade(regime_result: RegimeResult) -> bool:
    """
    Returns False if we're in CHOP regime with low confidence.
    Prevents the bot from over-trading in sideways markets.
    """
    if regime_result.regime == "CHOP" and regime_result.confidence >= 0.50:
        return False          # Hard chop — sit out
    return True              # BULL, BEAR, or borderline — trade with adaptive params


# ---------------------------------------------------------------------------
# Quick standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _test():
        print("Testing Regime Detector (live BTC 4h data)...")
        result = await get_regime()
        regime_icon = "[BULL]" if result.regime == "BULL" else "[BEAR]" if result.regime == "BEAR" else "[CHOP]"
        print(f"\n  Regime:       {regime_icon} {result.regime}")
        print(f"  Confidence:   {result.confidence:.1%}")
        print(f"  Scores:       Bull={result.bull_score}  Bear={result.bear_score}  Chop={result.chop_score}")
        print(f"  Should Trade: {should_trade(result)}")
        print(f"\n  Active Profile: {result.params['label']}")
        print(f"    RSI         : {result.params['rsi_lower']}-{result.params['rsi_upper']}")
        print(f"    ATR mult    : {result.params['atr_multiplier']}x")
        print(f"    Trail       : {result.params['trailing_activation_pct']*100:.1f}%/{result.params['trailing_pullback_pct']*100:.1f}%")
        print(f"    Vol filter  : {result.params['vol_sma_multiplier']:.2f}x SMA")
        print(f"\n  Detail breakdown:")
        for d in result.details.split(" | "):
            print(f"    - {d}")

    asyncio.run(_test())
