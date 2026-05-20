import asyncio
import os
import sys
from sqlalchemy import select, text
from decimal import Decimal

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade

async def check():
    async with get_session() as session:
        # Check Trade count
        res = await session.execute(select(Trade))
        trades = res.scalars().all()
        print(f"TRADES IN DB: {len(trades)}")
        
        # Check PaperTrade count
        res_pt = await session.execute(select(PaperTrade))
        pts = res_pt.scalars().all()
        print(f"PAPER_TRADES IN DB: {len(pts)}")
        
        if len(trades) > 0:
            print("--- FIRST 3 TRADES ---")
            for t in trades[:3]:
                print(f"ID: {t.id} ticker={t.ticker} side={t.side} is_closed={t.is_closed}")

async def run_migration():
    print("Re-running migration with per-item flush...")
    async with get_session() as session:
        # Clear existing
        await session.execute(text("DELETE FROM paper_trades"))
        await session.flush()
        
        res = await session.execute(select(Trade))
        trades = res.scalars().all()
        
        for t in trades:
            # Explicitly NOT assigning an ID to let SQLAlchemy generate a fresh one
            pt = PaperTrade(
                ticker=t.ticker,
                action="LONG" if (t.action == "BUY" or t.side == "BUY") else "SHORT",
                entry_price=float(t.price),
                exit_price=float(t.price) if t.is_closed else None,
                size_usdt=float(t.position_size_usdt or (float(t.amount) * float(t.price)) or 1000.0),
                status="CLOSED" if t.is_closed else "OPEN",
                ai_reasoning=t.reason or "Historical migration"
            )
            session.add(pt)
            # Flushing each to catch exactly WHICH one fails if it does
            try:
                await session.flush()
            except Exception as e:
                print(f"❌ Failed on trade {t.id}: {e}")
                raise
        
        await session.commit()
        print(f"✅ Migrated {len(trades)} entries.")

if __name__ == "__main__":
    asyncio.run(check())
    asyncio.run(run_migration())
