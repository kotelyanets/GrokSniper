import logging
from decimal import Decimal
from sqlalchemy import select

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade

logger = logging.getLogger(__name__)

async def fetch_recent_performance_memory(limit: int = 5) -> str:
    """
    Fetches the most recently closed trades (both live and paper) to generate 
    a 'Short-Term Memory' string for the AI agents to reflect upon past mistakes
    or successes.
    """
    try:
        async with get_session() as session:
            # Query recent closed Live Trades
            live_stmt = select(Trade).where(Trade.status == "closed").order_by(Trade.created_at.desc()).limit(limit)
            live_res = await session.execute(live_stmt)
            live_trades = live_res.scalars().all()

            # Query recent closed Paper Trades
            paper_stmt = select(PaperTrade).where(PaperTrade.status == "closed").order_by(PaperTrade.created_at.desc()).limit(limit)
            paper_res = await session.execute(paper_stmt)
            paper_trades = paper_res.scalars().all()

        # Combine, sort descending by time, and slice
        all_closed = sorted(live_trades + paper_trades, key=lambda x: x.created_at, reverse=True)[:limit]

        if not all_closed:
            return "No recent closed trades available. Start fresh."

        lines = ["--- RECENT PERFORMANCE MEMORY ---", "Reflect on these recent outcomes to adjust your strategy."]
        lines.append("If recent breakouts failed, be conservative. If trending, ride the momentum.\n")

        for idx, t in enumerate(all_closed, 1):
            # Calculate PnL %
            pnl_pct = 0.0
            if t.entry_price and t.exit_price and t.entry_price > 0:
                diff = float(t.exit_price) - float(t.entry_price)
                if t.side == "SHORT":
                    diff = -diff
                pnl_pct = (diff / float(t.entry_price)) * 100

            outcome_str = f"WIN +{pnl_pct:.2f}%" if pnl_pct > 0 else f"LOSS {pnl_pct:.2f}%"
            if pnl_pct == 0:
                outcome_str = "BREAKEVEN 0.00%"
                
            # Extract reasoning (handle both Live and Paper model differences)
            reason = getattr(t, "reason", "") or getattr(t, "ai_reasoning", "No reason provided.")
            
            lines.append(f"{idx}. [{outcome_str}] {t.action} {t.ticker}.")
            lines.append(f"   Reasoning: {reason}")
            lines.append(f"   Exit Info: entry=${t.entry_price or 0:.4f}, exit=${t.exit_price or 0:.4f}\n")

        memory_str = "\n".join(lines)
        logger.info("Generated Performance Memory (%d entries)", len(all_closed))
        return memory_str
        
    except Exception as e:
        logger.error("Failed to generate performance memory: %s", e)
        return "Error fetching memory. Assume neutral conditions."
