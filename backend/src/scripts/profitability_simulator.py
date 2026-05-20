"""
profitability_simulator.py
--------------------------
Phase 7: Monte Carlo projection script for estimating the time required 
to reach profit milestones ($10 -> $20, $10 -> $100) using historical 
or simulated bot metrics, explicitly accounting for realistic Binance exchange fees.

Usage: python -m backend.src.scripts.profitability_simulator
"""

import asyncio
import logging
import math
import os
import sys

import numpy as np
from sqlalchemy import select

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import PaperTrade
from backend.src.services.exchange import CryptoExchange

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("profit")

# Constants
MAKER_FEE = 0.0010  # 0.1% binance spot maker
TAKER_FEE = 0.0010  # 0.1% binance spot taker
ROUND_TRIP_FEE = MAKER_FEE + TAKER_FEE

async def simulate_profitability():
    logger.info("========================================")
    logger.info("  GROKSNIPER SMALL DEPOSIT SIMULATOR  ")
    logger.info("========================================")

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(PaperTrade).where(PaperTrade.status == "CLOSED")
            result = await session.execute(stmt)
            trades = result.scalars().all()
    except Exception as e:
        logger.error(f"Failed to access DB: {e}")
        sys.exit(1)

    # Base Metrics Calculation
    if not trades:
        logger.warning("No closed PaperTrades found. Using default pessimistic risk ratios.")
        win_rate = 0.55
        avg_win_pct = 0.04   # 4%
        avg_loss_pct = -0.03 # -3%
    else:
        wins, losses = [], []
        for t in trades:
            if not t.entry_price or not t.exit_price:
                continue
            
            pnl_pct = 0
            if t.action == "LONG":
                pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
            else:
                pnl_pct = (t.entry_price - t.exit_price) / t.entry_price
                
            if pnl_pct > 0:
                wins.append(pnl_pct)
            else:
                losses.append(pnl_pct)
                
        total = len(wins) + len(losses)
        win_rate = len(wins) / total if total > 0 else 0.55
        avg_win_pct = np.mean(wins) if wins else 0.04
        avg_loss_pct = np.mean(losses) if losses else -0.03
        
    logger.info(f"[1] Base Metrics (Net of estimated slippage):")
    logger.info(f"    Assumed Win Rate:      {win_rate*100:.1f}%")
    logger.info(f"    Assumed Avg Win:       {avg_win_pct*100:.2f}%")
    logger.info(f"    Assumed Avg Loss:      {avg_loss_pct*100:.2f}%")
    logger.info(f"    Exchange Fee:          {ROUND_TRIP_FEE*100:.2f}% Round Trip")
    
    # Time estimation
    scan_interval = int(os.getenv("SCAN_INTERVAL", "900"))  # Default 15 mins
    trades_per_day = (86400 / scan_interval) * 0.2 # assume bot finds a trade on 20% of scans
    logger.info(f"    Est. Trades/Day:       ~{trades_per_day:.1f}")
    logger.info("")

    # Simulation Scenarios
    scenarios = [10.0, 50.0, 100.0, 500.0]
    num_sims = 1000
    max_days = 365 # Stop simulating after a year
    max_trades = int(max_days * trades_per_day)

    logger.info("[2] Monte Carlo Milestones (1,000 runs, full compounding):")
    
    for deposit in scenarios:
        # We want to find days to double (x2) and days to 10x
        target_2x = deposit * 2
        target_10x = deposit * 10
        
        days_to_2x = []
        days_to_10x = []
        ruin_events = 0
        
        # Binance minimum volume is 10 USDT in most pairs.
        if deposit <= 10.0:
            logger.warning(f"  Deposit: ${deposit:.2f} — WARNING: Binance minimum trade size is $10. May hit exchange limits instantly on any loss.")

        for _ in range(num_sims):
            capital = deposit
            trades_taken = 0
            reached_2x = False
            
            while capital < target_10x and trades_taken < max_trades:
                # Kelly style full compounding (risky on $10, but requested to see 10x speed)
                pos_size = capital 
                
                if pos_size < 10.0: # Ruin / blocked by exchange min
                    ruin_events += 1
                    break
                
                is_win = np.random.random() < win_rate
                
                # Apply simulated PnL + Fees
                if is_win:
                    pnl_amt = pos_size * (avg_win_pct - ROUND_TRIP_FEE)
                else:
                    pnl_amt = pos_size * (avg_loss_pct - ROUND_TRIP_FEE)
                    
                capital += pnl_amt
                trades_taken += 1
                
                if not reached_2x and capital >= target_2x:
                    days_to_2x.append(trades_taken / trades_per_day)
                    reached_2x = True
                    
            if capital >= target_10x:
                days_to_10x.append(trades_taken / trades_per_day)

        median_days_2x = np.median(days_to_2x) if days_to_2x else -1
        median_days_10x = np.median(days_to_10x) if days_to_10x else -1
        ruin_prob = ruin_events / num_sims
        
        print_str = f"  Deposit: ${deposit:<6.2f} | "
        if ruin_prob > 0.5:
            print_str += f"FAILED ({ruin_prob*100:.0f}% risk of dropping below $10 exchange min)"
        else:
            d2 = f"{median_days_2x:.1f}d" if median_days_2x > 0 else "Never"
            d10 = f"{median_days_10x:.1f}d" if median_days_10x > 0 else "Never"
            print_str += f"Target 2x (${target_2x}): {d2:<6} | Target 10x (${target_10x}): {d10:<6}"
            
        logger.info(print_str)

    logger.info("")
    logger.info("========================================")
    
if __name__ == "__main__":
    asyncio.run(simulate_profitability())
