"""
position_reconciler.py
-----------------------
Ensures every open trade has an active WebSocket watcher.
Detects and fixes orphaned positions that lost their watchers
due to disconnections, crashes, or race conditions.

Runs every 60 seconds as a background task.
"""

import asyncio
import logging

from sqlalchemy import select

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade
from backend.src.services.ws_manager import _active_watchers, _watch_trade

logger = logging.getLogger("groksniper.reconciler")

RECONCILE_INTERVAL = 60  # seconds


async def reconcile_positions_loop() -> None:
    """
    Supervisor loop:
      1. Queries all OPEN BUY trades in the DB.
      2. Checks if each has an active watcher in ws_manager._active_watchers.
      3. Spawns missing watchers for orphaned trades.
      4. Reports stats every cycle.
    """
    logger.info("[Reconciler] Starting position reconciler loop (interval=%ds)...", RECONCILE_INTERVAL)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")  # noqa: E712
                result = await session.execute(stmt)
                open_trades = result.scalars().all()

            if not open_trades:
                await asyncio.sleep(RECONCILE_INTERVAL)
                continue

            # Prune dead watchers
            dead = [tid for tid, task in _active_watchers.items() if task.done()]
            for tid in dead:
                _active_watchers.pop(tid, None)

            # Check for orphans
            orphan_count = 0
            for trade in open_trades:
                tid = str(trade.id)
                if tid not in _active_watchers:
                    orphan_count += 1
                    side_label = trade.side or "LONG"
                    logger.warning(
                        "[Reconciler] ORPHAN detected: %s (%s, id=%s) — spawning watcher",
                        trade.ticker, side_label, tid[:8],
                    )
                    task = asyncio.create_task(
                        _watch_trade(tid),
                        name=f"reconciled_{trade.ticker}_{tid[:8]}",
                    )
                    _active_watchers[tid] = task

            if orphan_count > 0:
                logger.info(
                    "[Reconciler] Fixed %d orphan(s). Total open: %d, Active watchers: %d",
                    orphan_count, len(open_trades), len(_active_watchers),
                )

        except Exception as e:
            logger.error("[Reconciler] Loop error: %s", e, exc_info=True)

        await asyncio.sleep(RECONCILE_INTERVAL)
