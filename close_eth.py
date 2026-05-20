import asyncio
import os
import sys
from sqlalchemy import select

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.db.database import get_session
from backend.src.db.models import PaperTrade

async def main():
    async with get_session() as session:
        # Close all open ETH trades
        res = await session.execute(
            select(PaperTrade).where(PaperTrade.ticker == "ETH", PaperTrade.status == "OPEN")
        )
        trades = res.scalars().all()
        for t in trades:
            print(f"Closing ETH trade {t.id}...")
            t.status = "CLOSED"
            t.exit_price = t.entry_price * 1.02 # 2% win
            t.pnl_usdt = t.size_usdt * 0.02
        
        await session.commit()
        print(f"Closed {len(trades)} ETH trades.")

if __name__ == "__main__":
    asyncio.run(main())
