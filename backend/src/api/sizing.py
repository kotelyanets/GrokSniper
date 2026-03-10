"""
sizing.py
---------
Phase 47 — Kelly Criterion + ML Confidence + Volatility position sizing.

Public API:
    calculate_position_size(free_usdt, expected_return, atr, current_price)
        → (usdt_to_spend: float, sizing_reason: str)

All constants below are derived from the Phase 44.3 WFV-validated
stress-test Pareto-BALANCED profile (3-year BTC 1m backtest).
Update them after each new backtesting run.
"""

# ---------------------------------------------------------------------------
# WFV-validated strategy stats (Kelly inputs)
# ---------------------------------------------------------------------------
_KELLY_WIN_RATE = 0.52    # historical win rate (52 %)
_KELLY_AVG_WIN  = 4.20    # avg winning trade return (%)
_KELLY_AVG_LOSS = 2.80    # avg losing trade return (%)  — positive value
_KELLY_MAX_FRAC = 0.25    # hard cap: never risk more than 25 % of balance
_KELLY_SCALE    = 0.50    # fractional Kelly (half-Kelly) → reduces variance


def _kelly_fraction() -> float:
    """
    Full Kelly formula: f* = W - (1-W)/RR
    where W = win rate, RR = avg_win / avg_loss.
    Returns the HALF-Kelly fraction (×0.5) capped at _KELLY_MAX_FRAC.
    """
    W  = _KELLY_WIN_RATE
    RR = _KELLY_AVG_WIN / max(_KELLY_AVG_LOSS, 0.01)
    kelly_full = W - (1.0 - W) / RR
    kelly_full = max(kelly_full, 0.0)        # floor at 0 (Kelly can go negative)
    return min(kelly_full * _KELLY_SCALE, _KELLY_MAX_FRAC)


def calculate_position_size(
    free_usdt: float,
    expected_return: float,
    atr: float,
    current_price: float,
) -> tuple[float, str]:
    """
    Phase 47 — Kelly Criterion + ML Confidence + Volatility sizing.

    Steps:
      1. Compute Half-Kelly base fraction from historical win/loss stats.
      2. Scale up/down by ML confidence (expected_return signal).
      3. Apply an ATR volatility penalty to avoid over-sizing in choppy markets.
      4. Hard-cap at _KELLY_MAX_FRAC (25 %) to prevent ruin.

    Returns (usdt_to_spend, sizing_reason).
    """
    # ── 1. Kelly base fraction ──────────────────────────────────────────────
    kelly_frac = _kelly_fraction()           # e.g. 0.09 (9 % of balance)

    # ── 2. ML Confidence Multiplier ────────────────────────────────────────
    abs_ret = abs(expected_return)
    if abs_ret >= 0.03:
        ml_mult = 1.50                       # Strong conviction: up to 1.5× Kelly
    elif abs_ret >= 0.01:
        ml_mult = 1.0 + (abs_ret - 0.01) / 0.02 * 0.50   # 1.0—1.5×
    else:
        ml_mult = 0.50                       # Weak signal: half Kelly

    # ── 3. Volatility Penalty (ATR as % of price) ──────────────────────────
    vol_penalty = 1.0
    if current_price > 0:
        atr_pct = atr / current_price
        if atr_pct > 0.04:
            vol_penalty = 0.50              # Very choppy — halve size
        elif atr_pct > 0.02:
            vol_penalty = 1.0 - ((atr_pct - 0.02) / 0.02) * 0.50

    # ── 4. Combine & cap ───────────────────────────────────────────────────
    effective_frac = kelly_frac * ml_mult * vol_penalty
    effective_frac = min(effective_frac, _KELLY_MAX_FRAC)
    effective_frac = max(effective_frac, 0.01)  # always at least 1 %

    raw_size   = free_usdt * effective_frac
    # Ensure Binance minimum ($10), then apply hard cap — but never let the cap
    # go below the minimum (relevant only for very small balances < $40).
    min_size   = 10.0
    max_size   = max(free_usdt * _KELLY_MAX_FRAC, min_size)
    final_size = min(max(raw_size, min_size), max_size)

    # ── Reasoning string for Telegram ──────────────────────────────────────
    conf_str = "HighConf" if ml_mult > 1.2 else "NormConf" if ml_mult >= 0.8 else "LowConf"
    vol_str  = "HighVol" if vol_penalty < 0.7 else "NormVol"
    reason   = (
        f"Kelly {kelly_frac*100:.1f}% × {ml_mult:.2f}× ML × {vol_penalty:.2f}× Vol "
        f"= {effective_frac*100:.1f}% ({conf_str}, {vol_str})"
    )

    return final_size, reason
