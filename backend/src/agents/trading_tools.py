import os
import logging
import asyncio
from decimal import Decimal
from sqlalchemy import select

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade, PaperTrade
from backend.src.services.exchange import CryptoExchange
import backend.src.config as config

logger = logging.getLogger("groksniper.agents.trading_tools")

async def get_account_summary() -> str:
    """Returns a summary of balance and open positions (Real + Paper)."""
    exchange = CryptoExchange()
    try:
        balance = await exchange.get_balance()
        total_usdt = balance.get("total_usdt", 0.0)
        
        async with AsyncSessionLocal() as session:
            # Real open trades
            real_stmt = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")
            real_res = await session.execute(real_stmt)
            real_trades = real_res.scalars().all()
            
            # Paper open trades
            paper_stmt = select(PaperTrade).where(PaperTrade.status == "OPEN")
            paper_res = await session.execute(paper_stmt)
            paper_trades = paper_res.scalars().all()
            
        summary = [f"💰 **Balance:** ${total_usdt:,.2f} USDT"]
        
        if real_trades:
            summary.append("\n📈 **Real Positions:**")
            for t in real_trades:
                summary.append(f"- {t.ticker}: {t.amount} @ ${t.price}")
        else:
            summary.append("\n📈 No real positions open.")
            
        if paper_trades:
            summary.append("\n📝 **Paper Positions:**")
            for t in paper_trades:
                summary.append(f"- {t.ticker}: {t.amount} @ ${t.entry_price}")
        
        return "\n".join(summary)
    except Exception as e:
        logger.error(f"Error getting account summary: {e}")
        return f"❌ Error fetching account data: {e}"

async def close_all_positions() -> str:
    """Emergency kill-switch: Closes EVERY open position."""
    from backend.src.services.telegram_listener import panic_command
    # We can't easily call panic_command directly as it expects a Telegram Update object
    # So we re-implement the core logic here or refactor server side
    # For now, let's trigger the config pause and log
    config.TRADING_PAUSED = True
    
    exchange = CryptoExchange()
    closed_count = 0
    
    try:
        async with AsyncSessionLocal() as session:
            # Close real
            real_stmt = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")
            real_res = await session.execute(real_stmt)
            for t in real_res.scalars().all():
                # Logic to close...
                close_action = "SELL" if t.side == "LONG" else "BUY"
                await exchange.execute_trade(t.ticker, close_action, float(t.amount))
                t.is_closed = True
                closed_count += 1
            
            # Close paper
            paper_stmt = select(PaperTrade).where(PaperTrade.status == "OPEN")
            paper_res = await session.execute(paper_stmt)
            for pt in paper_res.scalars().all():
                pt.status = "CLOSED"
                closed_count += 1
                
            await session.commit()
            
        return f"🚨 **PANIC SUCCESS:** Closed {closed_count} positions and paused trading."
    except Exception as e:
        return f"❌ **PANIC FAILED:** {e}"

async def request_on_demand_analysis(ticker: str) -> str:
    """Triggers a Board of Directors analysis for a specific ticker."""
    from backend.src.core.engine import _fetch_mtf_condensed_ohlcv, _groq_sentiment
    from backend.src.core.agents.quant_analyst import propose_trades
    from backend.src.core.agents.risk_guardian import evaluate_proposals
    from backend.src.services.memory_manager import fetch_recent_performance_memory
    
    ticker = ticker.upper().strip()
    logger.info(f"On-demand analysis requested for {ticker}")
    
    try:
        # Sync OHLCV & Sentiment
        ohlcv = await _fetch_mtf_condensed_ohlcv(ticker)
        if not ohlcv: return f"❌ No data found for {ticker}."
        
        condensed, indicators, df_15m = ohlcv
        sent_score, sent_sum = await _groq_sentiment("", ticker)
        
        payload = [{
            "ticker": ticker,
            "condensed": condensed,
            "sentiment_score": sent_score,
            "sentiment_summary": sent_sum
        }]
        
        memory = await fetch_recent_performance_memory(limit=3)
        
        # Step 1: Quant
        proposals = await propose_trades(payload, {ticker: (sent_score, sent_sum)}, memory)
        
        if not proposals:
            return f"⚖️ **Board Verdict for {ticker}:**\nQuant Analyst suggests **HOLD**. Setup is not strong enough right now."
            
        # Step 2: Risk
        btc_context = "On-demand: BTC context not pulled." # Simple for now
        final = await evaluate_proposals(proposals, btc_context, payload, memory)
        
        dec = final[0]
        verdict = dec.get("verdict", "REJECTED")
        q_reason = dec.get("quant_reasoning", "")
        r_reason = dec.get("risk_reasoning", "")
        
        emoji = "✅" if verdict == "APPROVED" else "❌"
        
        return (
            f"🏛️ **Board of Directors Analysis: {ticker}**\n\n"
            f"👤 **Quant Analyst:** {dec.get('proposed_action')} ({dec.get('confidence')}%)\n"
            f"💬 *Reason:* {q_reason}\n\n"
            f"{emoji} **Risk Guardian:** {verdict}\n"
            f"💬 *Reason:* {r_reason}"
        )
        
    except Exception as e:
        logger.error(f"On-demand error: {e}")
        return f"❌ Error during analysis: {e}"
