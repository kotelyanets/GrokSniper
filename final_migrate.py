import asyncio
import os
import sys
from sqlalchemy import select, text

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade

async def main():
    print("Starting final migration...")
    async with get_session() as session:
        # 1. Clear existing PaperTrade
        await session.execute(text("DELETE FROM paper_trades"))
        await session.flush()
        
        # 2. Mirror ALL Trade entries
        res = await session.execute(select(Trade))
        trades = res.scalars().all()
        print(f"Found {len(trades)} trades in logs.")
        
        count = 0
        for t in trades:
            # Determine action
            action = "LONG"
            if t.side == "SHORT" or t.side == "SELL" or t.action == "SELL":
                action = "SHORT"
            
            # Safe float conversions
            try:
                entry_price = float(t.price)
                size_usdt = float(t.position_size_usdt or (float(t.amount) * float(t.price)) or 100.0)
                
                pt = PaperTrade(
                    ticker=t.ticker,
                    action=action,
                    entry_price=entry_price,
                    exit_price=entry_price if t.is_closed else None,
                    size_usdt=size_usdt,
                    status="CLOSED" if t.is_closed else "OPEN",
                    ai_reasoning=t.reason or "Historical migration"
                )
                session.add(pt)
                count += 1
            except Exception as e:
                print(f"Skipping trade {t.id} due to conversion error: {e}")
        
        await session.commit()
        print(f"Successfully migrated {count} trades.")

if __name__ == "__main__":
    asyncio.run(main())
