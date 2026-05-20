import asyncio
import os
import sys

# Add current directory to path to import backend
sys.path.append(os.getcwd())

from backend.src.api.routes import get_analytics

async def main():
    res = await get_analytics()
    print("ANALYTICS RESPONSE:")
    print(f"Total Trades: {res['total_trades']}")
    print(f"Win Rate: {res['win_rate']}%")
    print(f"Total PnL: ${res['total_pnl']}")

if __name__ == "__main__":
    asyncio.run(main())
