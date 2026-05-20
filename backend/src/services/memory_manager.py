"""
memory_manager.py — GrokSniper Adaptive Learning Memory
=========================================================
Generates rich, structured performance memory for the AI agents.
The AI uses this EVERY cycle to learn from past mistakes and adapt.

Components:
  1. Per-ticker Win/Loss breakdown
  2. Recent regime performance (is TRENDING_UP working?)
  3. Confidence calibration (did high-confidence trades win?)
  4. Adaptation score (0-100) for the dashboard
"""
import logging
from decimal import Decimal
from sqlalchemy import select, text

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade

logger = logging.getLogger(__name__)


async def fetch_recent_performance_memory(limit: int = 10) -> str:
    """
    Generates a rich 'Strategy Memory' string for the AI agents.
    Called every cycle. The AI must reflect on this before proposing new trades.
    """
    try:
        async with get_session() as session:
            # Get recent CLOSED PaperTrades (primary analytics source)
            paper_stmt = (
                select(PaperTrade)
                .where(PaperTrade.status == "CLOSED")
                .order_by(PaperTrade.created_at.desc())
                .limit(limit)
            )
            paper_res = await session.execute(paper_stmt)
            closed_trades = paper_res.scalars().all()

        if not closed_trades:
            return (
                "No closed trades in memory yet. This is the first cycle.\n"
                "Start fresh — propose conservative setups to begin building your track record."
            )

        # ── Build core statistics ──────────────────────────────────────────
        wins = [t for t in closed_trades if t.pnl_usdt and t.pnl_usdt > 0]
        losses = [t for t in closed_trades if t.pnl_usdt and t.pnl_usdt <= 0]
        total = len(closed_trades)
        win_rate = (len(wins) / total * 100) if total > 0 else 0

        # Per-ticker and Per-pattern performance
        ticker_stats: dict[str, dict] = {}
        pattern_stats: dict[str, dict] = {} # e.g., "BTC LONG"
        
        for t in closed_trades:
            if t.ticker not in ticker_stats:
                ticker_stats[t.ticker] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
            
            pattern_key = f"{t.ticker} {t.action}"
            if pattern_key not in pattern_stats:
                pattern_stats[pattern_key] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
            
            pnl = float(t.pnl_usdt or 0)
            if pnl > 0:
                ticker_stats[t.ticker]["wins"] += 1
                pattern_stats[pattern_key]["wins"] += 1
            else:
                ticker_stats[t.ticker]["losses"] += 1
                pattern_stats[pattern_key]["losses"] += 1
                
            ticker_stats[t.ticker]["total_pnl"] += pnl
            pattern_stats[pattern_key]["total_pnl"] += pnl

        # Recent trend (last 3 trades)
        recent_3 = closed_trades[:3]
        recent_pnls = [float(t.pnl_usdt or 0) for t in recent_3]
        recent_wins = sum(1 for p in recent_pnls if p > 0)
        momentum = "HOT STREAK" if recent_wins == 3 else "COLD STREAK" if recent_wins == 0 else "MIXED"

        # ── Compose the memory block ───────────────────────────────────────
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║       STRATEGY ADAPTATION MEMORY — READ CAREFULLY        ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            f"OVERALL PERFORMANCE ({total} closed trades):",
            f"  Win Rate: {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)",
            f"  Total PnL: ${sum(float(t.pnl_usdt or 0) for t in closed_trades):.2f}",
            f"  Recent Momentum (last 3): {momentum}",
            "",
        ]

        # Per-ticker breakdown
        lines.append("PER-TICKER SCORECARD:")
        for ticker, stats in sorted(ticker_stats.items()):
            ticker_wr = stats["wins"] / (stats["wins"] + stats["losses"]) * 100 if (stats["wins"] + stats["losses"]) > 0 else 0
            flag = "✓" if ticker_wr >= 50 else "✗"
            lines.append(
                f"  {flag} {ticker}: {ticker_wr:.0f}% win rate | PnL=${stats['total_pnl']:.2f}"
            )
        lines.append("")

        # Directive based on win rate
        lines.append("STRATEGY DIRECTIVES (apply these rules NOW):")
        if win_rate >= 70:
            lines.append("  → Win rate is EXCELLENT. Maintain current strategy parameters.")
            lines.append("  → You may slightly increase position sizes on high-confidence setups.")
        elif win_rate >= 50:
            lines.append("  → Win rate is ACCEPTABLE. Continue current approach with standard sizing.")
        elif win_rate >= 30:
            lines.append("  → Win rate is BELOW AVERAGE. Be more selective — only LONG/SHORT on very strong setups.")
            lines.append("  → Reduce position sizes by 30% until win rate improves.")
        else:
            lines.append("  → Win rate is CRITICALLY LOW. Enter DEFENSIVE MODE:")
            lines.append("  → ONLY propose HOLD unless RSI/MACD/OBI alignment is 3/3.")
            lines.append("  → Cut position sizes to minimum (3-5%) to preserve capital.")

        # Worst recent loss lesson
        if losses:
            worst = min(losses, key=lambda t: float(t.pnl_usdt or 0))
            lines.append("")
            lines.append(f"LESSON FROM WORST LOSS: {worst.ticker} {worst.action} → ${float(worst.pnl_usdt or 0):.2f}")
            if worst.ai_reasoning:
                lines.append(f"  Original reasoning: {worst.ai_reasoning[:150]}")
            lines.append("  → Identify what signal was wrong. Avoid repeating this mistake.")

        # Per-pattern directives for precise learning
        bad_patterns = []
        good_patterns = []
        for pattern, s in pattern_stats.items():
            total_pattern = s["wins"] + s["losses"]
            if total_pattern >= 3:
                wr = s["wins"] / total_pattern * 100
                if wr < 34:
                    bad_patterns.append(f"{pattern} (Win Rate: {wr:.0f}%, PnL: ${s['total_pnl']:.2f})")
                elif wr > 66:
                    good_patterns.append(f"{pattern} (Win Rate: {wr:.0f}%, PnL: ${s['total_pnl']:.2f})")

        if bad_patterns or good_patterns:
            lines.append("")
            lines.append("PATTERN RECOGNITION (Targeted Advice):")
            
            if bad_patterns:
                lines.append("  🛑 AVOID OR REDUCE SIZE FOR THESE HISTORICAL LOSERS:")
                for pat in bad_patterns:
                    lines.append(f"     - {pat} → Only trade if confidence > 85.")
                    
            if good_patterns:
                lines.append("  ✅ AGGRESSIVE OPPORTUNITIES (Proven Winners):")
                for pat in good_patterns:
                    lines.append(f"     - {pat} → Approved for standard or increased Kelly sizing.")

        lines.append("")
        lines.append("═" * 58)

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to generate performance memory: %s", e)
        return "Error fetching memory. Assume neutral conditions and trade conservatively."


async def get_adaptation_score() -> dict:
    """
    Computes the real-time Strategy Adaptation Score (0-100) for the dashboard.
    
    Score components:
      - 40pts: Win rate (recent 10 trades)
      - 30pts: PnL consistency (no single massive loss)
      - 20pts: Learning trend (improving over time?)
      - 10pts: Diversity (trading multiple tickers, not just one)
    
    Returns:
      {
        "score": 0-100,
        "label": "Calibrating"|"Learning"|"Adapting"|"Optimized",
        "win_rate": float,
        "total_trades": int,
        "details": {...}
      }
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(PaperTrade)
                .where(PaperTrade.status == "CLOSED")
                .order_by(PaperTrade.created_at.asc())
            )
            trades = result.scalars().all()

        if not trades:
            return {
                "score": 0,
                "label": "Calibrating",
                "win_rate": 0.0,
                "total_trades": 0,
                "details": {"message": "No closed trades yet. Bot is calibrating."}
            }

        pnls = [float(t.pnl_usdt or 0) for t in trades]
        total = len(trades)
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / total * 100

        # ── Component 1: Win rate score (40pts max) ──────────────────────
        wr_score = min(40, win_rate * 0.4)  # 100% wr = 40pts

        # ── Component 2: PnL consistency (30pts max) ─────────────────────
        total_pnl = sum(pnls)
        worst_loss = min(pnls) if pnls else 0
        # Penalize heavily if one trade lost > 20% of total gains
        if total_pnl > 0:
            loss_ratio = abs(worst_loss) / (total_pnl + abs(worst_loss))
            consistency_score = max(0, 30 * (1 - loss_ratio))
        else:
            consistency_score = 0.0

        # ── Component 3: Learning trend (20pts max) ───────────────────────
        # Is win rate improving? Compare first half vs second half
        trend_score = 0.0
        if total >= 4:
            half = total // 2
            first_wr = sum(1 for p in pnls[:half] if p > 0) / half
            second_wr = sum(1 for p in pnls[half:] if p > 0) / (total - half)
            if second_wr > first_wr:
                trend_score = min(20, (second_wr - first_wr) * 200)  # max 20pts for 10% improvement
            elif second_wr == first_wr and first_wr > 0:
                trend_score = 10  # stable is worth half
        elif total >= 1:
            trend_score = 10  # some data = some credit

        # ── Component 4: Diversity (10pts max) ────────────────────────────
        unique_tickers = len(set(t.ticker for t in trades))
        diversity_score = min(10, unique_tickers * 2.5)  # 4+ tickers = max

        # Total score
        raw_score = wr_score + consistency_score + trend_score + diversity_score
        final_score = min(100, max(0, round(raw_score)))

        # Label
        if final_score >= 80:
            label = "Optimized"
        elif final_score >= 55:
            label = "Adapting"
        elif final_score >= 25:
            label = "Learning"
        else:
            label = "Calibrating"

        return {
            "score": final_score,
            "label": label,
            "win_rate": round(win_rate, 1),
            "total_trades": total,
            "details": {
                "win_rate_pts": round(wr_score, 1),
                "consistency_pts": round(consistency_score, 1),
                "trend_pts": round(trend_score, 1),
                "diversity_pts": round(diversity_score, 1),
                "total_pnl": round(total_pnl, 2),
                "worst_loss": round(worst_loss, 2),
                "unique_tickers": unique_tickers,
            }
        }

    except Exception as e:
        logger.error("Failed to compute adaptation score: %s", e)
        return {"score": 0, "label": "Error", "win_rate": 0.0, "total_trades": 0, "details": {}}

async def get_rolling_win_rate(window: int = 20) -> float:
    """
    Returns the latest N-trade win rate for real-time monitoring.
    Used for Strategy Verification (Phase 3).
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(PaperTrade)
                .where(PaperTrade.status == "CLOSED")
                .order_by(PaperTrade.created_at.desc())
                .limit(window)
            )
            trades = result.scalars().all()

        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.pnl_usdt and t.pnl_usdt > 0)
        return float(wins) / len(trades)
    except Exception as e:
        logger.error(f"Failed to calculate rolling win rate: {e}")
        return 0.0
