"""
strategy_verifier.py
--------------------
Phase 3 Script that loads all closed PaperTrade records, computes key strategy metrics,
runs Monte Carlo simulation on the current P&L distribution, and prints a PASS/FAIL verdict.

Usage: python -m backend.src.scripts.strategy_verifier
"""

import asyncio
import logging
import math
import sys
from collections import defaultdict

import numpy as np
from sqlalchemy import select

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import PaperTrade

# Set up logging for CLI output
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verifier")

async def verify_strategy():
    """Main verification logic."""
    logger.info("========================================")
    logger.info("   GROKSNIPER STRATEGY VERIFICATION     ")
    logger.info("========================================")

    try:
        async with AsyncSessionLocal() as session:
            # Load all closed paper trades
            stmt = select(PaperTrade).where(PaperTrade.status == "CLOSED").order_by(PaperTrade.created_at.desc())
            result = await session.execute(stmt)
            trades = result.scalars().all()
    except Exception as e:
        logger.error(f"Failed to access DB: {e}")
        sys.exit(1)

    if not trades:
        logger.warning("No closed PaperTrades found in database.")
        logger.warning("Bot requires trades to verify strategy performance.")
        sys.exit(0)

    # 1. Compute Historical Performance
    pnls = [float(t.pnl_usdt) for t in trades if t.pnl_usdt is not None]
    if not pnls:
        logger.warning("No valid PnL records found.")
        sys.exit(0)

    total_trades = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / total_trades
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    profit_factor = sum(wins) / abs(sum(losses)) if sum(losses) != 0 else float("inf")
    
    # Kelly Criterion Calculation
    kelly_fraction = 0.0
    if avg_loss < 0:
        rr_ratio = avg_win / abs(avg_loss)
        if rr_ratio > 0:
            kelly_fraction = max(0.0, win_rate - (1.0 - win_rate) / rr_ratio)
            
    # Simple Max Drawdown Approximation
    cumulative_pnl = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative_pnl)
    drawdowns = running_max - cumulative_pnl
    max_drawdown = float(drawdowns.max() if len(drawdowns) > 0 else 0)

    logger.info(f"[1] Historical Performance ({total_trades} trades):")
    logger.info(f"    Win Rate:      {win_rate*100:.1f}%")
    logger.info(f"    Avg Win:       ${avg_win:.2f}")
    logger.info(f"    Avg Loss:      ${avg_loss:.2f}")
    logger.info(f"    Profit Factor: {profit_factor:.2f}")
    logger.info(f"    Kelly Size:    {kelly_fraction*100:.1f}%")
    logger.info(f"    Max Drawdown:  ${max_drawdown:.2f}")
    logger.info("")

    # 2. Monte Carlo Simulation (1,000 runs, 100 trades each)
    logger.info("[2] Monte Carlo Risk Simulation:")
    if len(pnls) < 10:
        logger.warning("    Not enough trades for reliable Monte Carlo (need 10+). Skipping.")
        ruin_prob = 1.0 # default fail
    else:
        num_sims = 1000
        trades_per_sim = 100
        ruin_limit = -100.0 # Define ruin as losing $100

        ruin_count = 0
        final_eqs = []

        for _ in range(num_sims):
            # Resample with replacement from actual trade PnLs
            sim_pnls = np.random.choice(pnls, size=trades_per_sim, replace=True)
            sim_cum = np.cumsum(sim_pnls)
            
            # Did we go below ruin limit?
            if np.any(sim_cum < ruin_limit):
                ruin_count += 1
                
            final_eqs.append(sim_cum[-1])

        ruin_prob = ruin_count / num_sims
        avg_final_eq = np.mean(final_eqs)

        logger.info(f"    Simulations:   {num_sims} (100 trades each)")
        logger.info(f"    Ruin Prob:     {ruin_prob*100:.1f}% (Risk of losing ${abs(ruin_limit)})")
        logger.info(f"    Expected PnL:  ${avg_final_eq:+.2f}")
    
    logger.info("")

    # 3. Verdict
    logger.info("[3] Verification Verdict:")
    passed = True
    
    if win_rate < 0.50:
        logger.error("    ❌ FAIL: Win rate is below 50%.")
        passed = False
    else:
        logger.info(f"    ✅ PASS: Win rate is above 50% ({win_rate*100:.1f}%).")
        
    if profit_factor < 1.25 and profit_factor != float("inf"):
        logger.error("    ❌ FAIL: Profit Factor is below 1.25.")
        passed = False
    else:
        logger.info(f"    ✅ PASS: Profit Factor is healthy ({profit_factor:.2f}).")
        
    if ruin_prob > 0.05: # > 5% risk of ruin
        logger.error("    ❌ FAIL: Monte Carlo risk of ruin > 5%. Strategy too volatile.")
        passed = False
    elif len(pnls) >= 10:
        logger.info(f"    ✅ PASS: Risk of ruin acceptable ({ruin_prob*100:.1f}%).")

    logger.info("========================================")
    if passed:
        logger.info("    🏆 STRATEGY VERIFIED: DEPLOYABLE")
    else:
        logger.warning("    ⚠️ STRATEGY BLOCKED: NEEDS TUNING")
    logger.info("========================================")

if __name__ == "__main__":
    asyncio.run(verify_strategy())
