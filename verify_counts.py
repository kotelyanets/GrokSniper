import asyncio
import os
import sys
from sqlalchemy import select

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.db.database import get_session
from backend.src.db.models import Trade, PaperTrade

async def main():
    async with get_session() as session:
        res = await session.execute(select(Trade))
        trades = res.scalars().all()
        
        res_pt = await session.execute(select(PaperTrade))
        pts = res_pt.scalars().all()
        
        print(f"TRADES_TOTAL: {len(trades)}")
        print(f"PAPER_TRADES_TOTAL: {len(pts)}")

if __name__ == "__main__":
    asyncio.run(main())
