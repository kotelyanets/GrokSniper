import asyncio
import os
import sys
from decimal import Decimal

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade
from sqlalchemy import select, text

async def migrate():
    print("Starting trade migration to analytics...")
    async with get_session() as session:
        # 0. Clear existing PaperTrade to avoid duplicates during mirror
        await session.execute(text("DELETE FROM paper_trades"))
        
        # 1. Fetch ALL trades
        res = await session.execute(select(Trade))
        all_trades = res.scalars().all()
        
        print(f"Found {len(all_trades)} trades in logs.")
        
        count = 0
        for t in all_trades:
            # Create a PaperTrade for every log entry to ensure data is visible
            # We'll mark them as CLOSED if is_closed is True
            pt = PaperTrade(
                ticker=t.ticker,
                action="LONG" if (t.action == "BUY" or t.side == "BUY") else "SHORT",
                entry_price=float(t.price),
                exit_price=float(t.price) if t.is_closed else None,
                size_usdt=float(t.position_size_usdt or (t.amount * t.price) or 1000.0),
                status="CLOSED" if t.is_closed else "OPEN",
                ai_reasoning=t.reason or "Historical trade"
            )
            session.add(pt)
            count += 1
            
        await session.commit()
        print(f"Migration complete! {count} trade entries mirrored to analytics.")

if __name__ == "__main__":
    asyncio.run(migrate())
