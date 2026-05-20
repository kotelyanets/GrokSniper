"""
capital_manager.py
------------------
Phase 5: Portfolio-level risk controller.

Enforces:
1. Max total exposure (e.g., max 40% of balance at risk across all trades)
2. Max per-ticker exposure (e.g., max 20% in one coin)
3. Drawdown circuit breaker (e.g., if trailing 24h PnL < -15% of balance, HOLD only)
4. Correlation guard (reduces size if buying highly correlated assets simultaneously)
"""

import logging
from sqlalchemy import select, text
from backend.src.db.models import Trade, PaperTrade

logger = logging.getLogger("groksniper.capital")


class CapitalManager:
    def __init__(self, max_total_exposure: float = 0.40, max_ticker_exposure: float = 0.20, max_drawdown: float = 0.15):
        """
        Args:
            max_total_exposure: Max % of total balance allowed in active trades.
            max_ticker_exposure: Max % of total balance allowed in a single active ticker.
            max_drawdown: Max % of balance that can be lost in last 24h before circuit breaks.
        """
        self.max_total_exposure = max_total_exposure
        self.max_ticker_exposure = max_ticker_exposure
        self.max_drawdown = max_drawdown
        
        # Simple correlation map — if holding key, reduce size of value by 50%
        self.correlation_map = {
            "BTC": ["ETH", "SOL", "BCH", "LTC"],
            "ETH": ["OP", "ARB", "LDO"],
            "DOGE": ["SHIB", "PEPE", "WIF"]
        }


    async def evaluate_trade(self,
                             db_session,
                             ticker: str,
                             proposed_action: str,
                             proposed_usdt: float,
                             total_balance: float,
                             is_paper: bool = False) -> tuple[bool, float, str]:
        """
        Evaluates a proposed trade against portfolio-level risk limits.

        Returns:
            (is_approved, adjusted_usdt, reason)
        """
        if proposed_action == "HOLD":
            return False, 0.0, "Action is HOLD"

        if total_balance <= 0 or proposed_usdt <= 0:
            return False, 0.0, "Invalid balance or trade amount"

        # 1. Fetch current open positions
        if is_paper:
            stmt = select(PaperTrade).where(PaperTrade.status == "OPEN")
            res = await db_session.execute(stmt)
            open_positions = res.scalars().all()
            
            # Map PaperTrade to standard structure
            current_exposure_total = sum(float(t.size_usdt) for t in open_positions)
            current_exposure_ticker = sum(float(t.size_usdt) for t in open_positions if t.ticker == ticker)
            active_tickers = [t.ticker for t in open_positions]
            
            # Drawdown check (last 24h closed trades)
            dd_stmt = text(
                "SELECT SUM(pnl_usdt) FROM paper_trades "
                "WHERE status = 'CLOSED' AND created_at >= NOW() - INTERVAL '24 HOURS'"
            )
            dd_res = await db_session.execute(dd_stmt)
            pnl_24h = float(dd_res.scalar() or 0.0)
            
        else:
            stmt = select(Trade).where(Trade.is_closed == False)
            res = await db_session.execute(stmt)
            open_positions = res.scalars().all()
            
            # For live trades, amount is in base currency, need to convert or we saved position_size_usdt
            current_exposure_total = sum(float(t.position_size_usdt or 0) for t in open_positions)
            current_exposure_ticker = sum(float(t.position_size_usdt or 0) for t in open_positions if t.ticker == ticker)
            active_tickers = [t.ticker for t in open_positions]
            
            # Real 24h PnL (approximate from closed trades)
            dd_stmt = text("""
                SELECT SUM((t2.price - t1.price) * t2.amount) as pnl
                FROM trades t2
                JOIN trades t1 ON t2.parent_id = t1.id
                WHERE t2.is_closed = true AND t2.created_at >= NOW() - INTERVAL '24 HOURS'
            """)
            dd_res = await db_session.execute(dd_stmt)
            pnl_24h = float(dd_res.scalar() or 0.0)

        # 2. Drawdown Circuit Breaker
        if pnl_24h < 0 and abs(pnl_24h) > (total_balance * self.max_drawdown):
            msg = f"CIRCUIT BREAKER: 24h loss (${abs(pnl_24h):.2f}) exceeds {self.max_drawdown*100}% of balance."
            logger.warning(msg)
            return False, 0.0, msg

        # 3. Max Ticker Exposure Guard
        available_for_ticker = (total_balance * self.max_ticker_exposure) - current_exposure_ticker
        if available_for_ticker <= 0:
            msg = f"EXPOSURE LIMIT: Already at max {self.max_ticker_exposure*100}% capacity for {ticker}."
            return False, 0.0, msg
        
        allowed_usdt = min(proposed_usdt, available_for_ticker)

        # 4. Max Total Exposure Guard
        available_total = (total_balance * self.max_total_exposure) - current_exposure_total
        if available_total <= 0:
            msg = f"PORTFOLIO LIMIT: Total exposure exceeds {self.max_total_exposure*100}% limit."
            return False, 0.0, msg
            
        allowed_usdt = min(allowed_usdt, available_total)

        # 5. Correlation Reduction
        correlation_penalty = 1.0
        for leader, followers in self.correlation_map.items():
            if leader in active_tickers and ticker in followers:
                correlation_penalty = 0.5
                break
            elif ticker == leader and any(f in active_tickers for f in followers):
                correlation_penalty = 0.5
                break

        if correlation_penalty < 1.0:
            allowed_usdt *= correlation_penalty
            logger.info(f"CORRELATION GUARD: Reducing size of {ticker} by 50% due to correlated asset holds.")

        # If after everything size is too small (e.g., < $10 Binance min), reject
        if allowed_usdt < 10.0:
            return False, 0.0, f"Allowed size (${allowed_usdt:.2f}) below exchange minimum."

        # Success
        if allowed_usdt < proposed_usdt:
            msg = f"Capital Manager reduced size from ${proposed_usdt:.2f} to ${allowed_usdt:.2f} (Exposure/Correlation Limits)."
        else:
            msg = "Capital limits OK."

        return True, allowed_usdt, msg

# Global singleton instance
global_capital_manager = CapitalManager()
