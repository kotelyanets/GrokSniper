import asyncio
import logging
from backend.src.core.engine import scan_all_tickers

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')

async def main():
    print("Starting direct engine test...")
    results = await scan_all_tickers()
    print("Results:", results)

asyncio.run(main())
