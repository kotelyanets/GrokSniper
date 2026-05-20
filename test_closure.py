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
        # Close the SOL trade as a test
        res = await session.execute(
            select(PaperTrade).where(PaperTrade.ticker == "SOL", PaperTrade.status == "OPEN").limit(1)
        )
        trade = res.scalar_one_or_none()
        if trade:
            print(f"Closing SOL trade {trade.id}...")
            trade.status = "CLOSED"
            trade.exit_price = trade.entry_price * 1.05 # Mock a win
            trade.pnl_usdt = trade.size_usdt * 0.05
            await session.commit()
            print("Trade closed successfully.")
        else:
            print("No open SOL trade found.")

if __name__ == "__main__":
    asyncio.run(main())
