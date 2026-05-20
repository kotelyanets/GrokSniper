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
        res = await session.execute(select(PaperTrade))
        trades = res.scalars().all()
        print("PAPER TRADES DETAILS:")
        for t in trades:
            print(f"Ticker: {t.ticker}, Status: {t.status}, PnL: {t.pnl_usdt}")

if __name__ == "__main__":
    asyncio.run(main())
