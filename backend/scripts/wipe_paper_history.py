"""
wipe_paper_history.py
─────────────────────
Hard-reset script: truncates all trading-related tables and flushes Redis.
Run this ONCE when switching from paper-trade mode to live mode so the
dashboard starts from a clean slate.

Usage:
    python -m backend.scripts.wipe_paper_history
    OR
    backend\venv\Scripts\python.exe -m backend.scripts.wipe_paper_history
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# ── Make sure the project root is importable ──────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text
from backend.src.db.database import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wipe_paper_history")

# Tables to wipe (order matters to avoid FK violations)
TABLES = [
    "trades",
    "paper_trades",
    "news_logs",
    "agent_decision_logs",
]


async def wipe_db() -> dict[str, int]:
    """Delete all rows from every trading table. Returns row counts per table."""
    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        for table in TABLES:
            try:
                result = await session.execute(text(f"DELETE FROM {table}"))
                counts[table] = result.rowcount
                logger.info("✓ Wiped %-30s  (%d rows deleted)", table, result.rowcount)
            except Exception as exc:
                logger.warning("⚠ Could not wipe %s: %s", table, exc)
                counts[table] = -1

        await session.commit()
        logger.info("✓ DB commit complete.")
    return counts


async def flush_redis() -> bool:
    """
    Flush all keys from the Redis instance (DB 0).
    Gracefully skips if Redis is not reachable or not installed.
    """
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.info("REDIS_URL not set — skipping Redis flush.")
        return False

    try:
        import redis.asyncio as aioredis  # type: ignore
        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.flushdb()
        await client.aclose()
        logger.info("✓ Redis DB 0 flushed successfully.")
        return True
    except ImportError:
        logger.info("redis[asyncio] not installed — skipping Redis flush (no stale state expected).")
        return False
    except Exception as exc:
        logger.warning("⚠ Redis flush failed (non-fatal): %s", exc)
        return False


async def main():
    logger.info("=" * 60)
    logger.info("  GrokSniper — Hard Reset (Paper → Live Transition)")
    logger.info("=" * 60)

    # Safety guard: require explicit confirmation
    print("\n⚠️  WARNING: This will permanently delete ALL rows from:")
    for t in TABLES:
        print(f"   • {t}")
    print("\nThis is required when transitioning from PAPER_TRADE to LIVE mode.")
    answer = input("\nType 'WIPE' to confirm: ").strip()
    if answer != "WIPE":
        print("Aborted — nothing was changed.")
        return

    logger.info("Starting database wipe...")
    counts = await wipe_db()

    logger.info("Flushing Redis cache...")
    redis_ok = await flush_redis()

    logger.info("=" * 60)
    logger.info("  RESET COMPLETE")
    logger.info("=" * 60)
    for table, n in counts.items():
        status = f"{n} rows deleted" if n >= 0 else "skipped (error)"
        logger.info("  %-30s  %s", table, status)
    logger.info("  Redis flush: %s", "✓ done" if redis_ok else "skipped")
    logger.info("")
    logger.info("  The bot will now start fresh with live Binance data.")
    logger.info("  Restart the FastAPI server to apply changes.")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
