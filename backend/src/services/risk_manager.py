"""
Phase 46 (Requested) — Dynamic Position Sizing via Kelly Criterion
==================================================================
Provides a data-driven position sizer that reads actual historical
trade performance from the database and computes the optimal bet size
using the Half-Kelly formula.

Math:
  R   = avg_win / |avg_loss|           (Risk/Reward ratio)
  K   = win_rate - (1 - win_rate) / R  (Full Kelly fraction)
  K_h = K * fraction                   (Half-Kelly — reduces variance 50%)

Safety:
  - Minimum bet: 1% of balance  (avoids rounding edge-cases)
  - Maximum bet: 20% of balance (hard cap to prevent reckless position)
  - Fallback: 5% if < 10 closed trades in history

Usage:
  from backend.src.services.risk_manager import get_dynamic_position_size

  async with AsyncSessionLocal() as session:
      usdt = await get_dynamic_position_size(session, balance=1000.0)
"""

import logging
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("groksniper.risk_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KELLY_FRACTION   = 0.50   # Half-Kelly dampener (reduces variance significantly)
MIN_KELLY        = 0.01   # 1%  — minimum safe bet fraction
MAX_KELLY        = 0.20   # 20% — hard cap; never bet more than this
FALLBACK_FRACTION = 0.05  # 5%  — used when < MIN_TRADES history is available
MIN_TRADES       = 10     # Minimum closed trades to use Kelly; else use fallback
LOOKBACK_TRADES  = 50     # How many recent closed trades to analyse


# ---------------------------------------------------------------------------
# 1. Kelly Maths (pure function, easily unit-testable)
# ---------------------------------------------------------------------------

def calculate_kelly_percentage(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = KELLY_FRACTION,
) -> float:
    """
    Compute the Half-Kelly position fraction.

    Args:
        win_rate: Fraction of winning trades, e.g. 0.55 for 55%
        avg_win:  Average PnL of winning trades (positive USDT)
        avg_loss: Average PnL of losing trades  (positive magnitude, e.g. 8.5)
        fraction: Kelly dampening factor (default 0.5 = Half-Kelly)

    Returns:
        A fraction in [MIN_KELLY, MAX_KELLY] representing how much of
        the balance to bet on this trade.
    """
    if avg_loss <= 0.0:
        logger.warning("[Kelly] avg_loss is zero or negative — using fallback fraction")
        return FALLBACK_FRACTION

    R = avg_win / avg_loss                         # Risk/Reward ratio
    K = win_rate - (1.0 - win_rate) / R            # Full Kelly: W - (1-W)/R
    safe_k = K * fraction                           # Half-Kelly

    logger.info(
        f"[Kelly] win_rate={win_rate:.1%}  avg_win={avg_win:.2f}  avg_loss={avg_loss:.2f}  "
        f"R={R:.2f}  K_full={K:.3f}  K_half={safe_k:.3f}"
    )

    if safe_k <= 0.0:
        logger.info("[Kelly] Negative Kelly — using MIN_KELLY (1%)")
        return MIN_KELLY

    result = min(max(safe_k, MIN_KELLY), MAX_KELLY)
    logger.info(f"[Kelly] Final fraction: {result:.1%} of balance")
    return result


# ---------------------------------------------------------------------------
# 2. DB Trade Aggregation
# ---------------------------------------------------------------------------

async def _get_closed_paper_trades(session: AsyncSession) -> list:
    """Fetch the last LOOKBACK_TRADES closed PaperTrades (most recent first)."""
    from backend.src.db.models import PaperTrade
    result = await session.execute(
        select(PaperTrade)
        .where(PaperTrade.status == "CLOSED")
        .order_by(PaperTrade.created_at.desc())
        .limit(LOOKBACK_TRADES)
    )
    return result.scalars().all()


async def _get_closed_live_trades(session: AsyncSession) -> list:
    """Fetch the last LOOKBACK_TRADES completed live Trades (most recent first)."""
    from backend.src.db.models import Trade
    result = await session.execute(
        select(Trade)
        .where(Trade.is_closed == True)  # noqa: E712
        .order_by(Trade.created_at.desc())
        .limit(LOOKBACK_TRADES)
    )
    return result.scalars().all()


def _compute_stats_from_paper_trades(trades) -> Optional[dict]:
    """
    Extract win_rate, avg_win, avg_loss from PaperTrade records.
    PaperTrade has `pnl_usdt` which is the signed net P&L.
    """
    closed = [t for t in trades if t.pnl_usdt is not None]
    if len(closed) < MIN_TRADES:
        return None

    wins  = [t.pnl_usdt for t in closed if t.pnl_usdt > 0]
    losses = [abs(t.pnl_usdt) for t in closed if t.pnl_usdt <= 0]

    if not wins or not losses:
        return None

    return {
        "win_rate": len(wins) / len(closed),
        "avg_win":  sum(wins)   / len(wins),
        "avg_loss": sum(losses) / len(losses),
        "n_trades": len(closed),
    }


def _compute_stats_from_live_trades(trades) -> Optional[dict]:
    """
    Pair BUY/SELL trades and compute net P&L per round-trip.
    For live trades, we reconstruct PnL from (entry price * qty) comparisons.
    Simple heuristic: if a trade has position_size_usdt, use that as a proxy.
    """
    from backend.src.db.models import Trade  # noqa: F401
    closed = [t for t in trades if t.is_closed]

    if len(closed) < MIN_TRADES:
        return None

    # Try to use stop_loss_price as a proxy loss indicator
    wins   = []
    losses = []

    for t in closed:
        if t.reason and "profit" in t.reason.lower():
            wins.append(t.position_size_usdt or 50.0)
        elif t.highest_price and t.price:
            # Trade closed at a gain if highest_price > entry price (LONG)
            gain = float(t.highest_price) - float(t.price)
            if gain > 0:
                wins.append(gain * float(t.amount))
            else:
                losses.append(abs(gain) * float(t.amount))

    if not wins or not losses:
        return None

    return {
        "win_rate": len(wins) / (len(wins) + len(losses)),
        "avg_win":  sum(wins)   / len(wins),
        "avg_loss": sum(losses) / len(losses),
        "n_trades": len(wins) + len(losses),
    }


# ---------------------------------------------------------------------------
# 3. Public API
# ---------------------------------------------------------------------------

async def get_dynamic_position_size(
    db_session: AsyncSession,
    current_balance: float,
    paper_trade: bool = True,
) -> tuple[float, str]:
    """
    Compute the optimal trade size in USDT using the Half-Kelly criterion
    derived from real historical trade statistics.

    Args:
        db_session:      Active async SQLAlchemy session.
        current_balance: Current USDT balance (free capital).
        paper_trade:     If True, query PaperTrade table; else Trade table.

    Returns:
        (usdt_to_spend, description_string)
        description_string is formatted for Telegram/logging.
    """
    stats = None

    try:
        if paper_trade:
            trades = await _get_closed_paper_trades(db_session)
            stats  = _compute_stats_from_paper_trades(trades)
        else:
            trades = await _get_closed_live_trades(db_session)
            stats  = _compute_stats_from_live_trades(trades)
    except Exception as e:
        logger.warning(f"[Kelly] DB query failed: {e}. Using static fallback.")

    if stats is None:
        # Not enough history — use safe fixed fraction
        fallback_usdt = current_balance * FALLBACK_FRACTION
        description = (
            f"Kelly: FALLBACK (< {MIN_TRADES} closed trades) | "
            f"{FALLBACK_FRACTION:.0%} × ${current_balance:.0f} = ${fallback_usdt:.2f}"
        )
        logger.info(f"[Kelly] {description}")
        return fallback_usdt, description

    kelly_pct = calculate_kelly_percentage(
        win_rate=stats["win_rate"],
        avg_win=stats["avg_win"],
        avg_loss=stats["avg_loss"],
    )

    usdt_to_spend = current_balance * kelly_pct

    # Safety floor: never go below $10 (Binance minimum)
    usdt_to_spend = max(usdt_to_spend, 10.0)

    description = (
        f"Kelly {kelly_pct:.1%} (WR={stats['win_rate']:.1%}, "
        f"avgW=${stats['avg_win']:.1f}, avgL=${stats['avg_loss']:.1f}, "
        f"n={stats['n_trades']}) → ${usdt_to_spend:.2f}"
    )
    logger.info(f"[Kelly] {description}")
    return usdt_to_spend, description
