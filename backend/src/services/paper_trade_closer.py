"""
paper_trade_closer.py
---------------------
Background loop that automatically closes PaperTrade positions when their
Stop-Loss or Take-Profit levels are hit by the current market price.

Architecture:
  - Runs every 30 seconds as a background asyncio task.
  - Fetches ALL open PaperTrades from the database.
  - For each, gets the live market price via the Exchange oracle.
  - Checks SL/TP conditions (inverted for SHORT positions).
  - On trigger: marks CLOSED, computes PnL, sends Telegram alert.

This is the CRITICAL missing piece — without it, paper trades stay OPEN forever.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from backend.src.api.state import broadcast_to_dashboard
from backend.src.db.database import get_session, AsyncSessionLocal
from backend.src.db.models import PaperTrade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message
from backend.src.services.email_notifier import send_email

logger = logging.getLogger("groksniper.paper_closer")

_exchange = CryptoExchange()

POLL_INTERVAL = int(os.getenv("PAPER_CLOSER_INTERVAL", "30"))  # seconds


# ---------------------------------------------------------------------------
# Core: check and close one trade
# ---------------------------------------------------------------------------

async def _check_and_close_trade(trade: PaperTrade, current_price: float) -> bool:
    """
    Evaluates SL/TP conditions for a single PaperTrade.
    Returns True if the trade was closed, False otherwise.
    """
    if current_price <= 0:
        return False

    entry = trade.entry_price
    sl = trade.stop_loss
    tp = trade.take_profit
    action = trade.action.upper()  # "LONG" or "SHORT"

    should_close = False
    exit_reason = ""
    exit_price = current_price

    if action == "LONG":
        if sl > 0 and current_price <= sl:
            should_close = True
            exit_reason = f"⛔ STOP-LOSS сработал (SL=${sl:,.2f})"
            exit_price = sl  # assume fill at SL level
        elif tp > 0 and current_price >= tp:
            should_close = True
            exit_reason = f"✅ TAKE-PROFIT достигнут (TP=${tp:,.2f})"
            exit_price = tp  # assume fill at TP level

    elif action == "SHORT":
        if sl > 0 and current_price >= sl:
            should_close = True
            exit_reason = f"⛔ SHORT STOP-LOSS сработал (SL=${sl:,.2f})"
            exit_price = sl
        elif tp > 0 and current_price <= tp:
            should_close = True
            exit_reason = f"✅ SHORT TAKE-PROFIT достигнут (TP=${tp:,.2f})"
            exit_price = tp

    if not should_close:
        return False

    # Compute PnL
    if action == "LONG":
        pnl_pct = ((exit_price - entry) / entry) * 100
        pnl_usdt = (exit_price - entry) / entry * trade.size_usdt
    else:  # SHORT
        pnl_pct = ((entry - exit_price) / entry) * 100
        pnl_usdt = (entry - exit_price) / entry * trade.size_usdt

    # Update DB
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == trade.id)
            )
            db_trade = result.scalar_one_or_none()
            if db_trade is None or db_trade.status == "CLOSED":
                return False  # Already closed by another process

            db_trade.status = "CLOSED"
            db_trade.exit_price = exit_price
            db_trade.pnl_usdt = pnl_usdt
            await session.commit()

            logger.info(
                "[PaperCloser] CLOSED %s %s | Entry=$%.4f → Exit=$%.4f | PnL=$%.2f (%.2f%%)",
                trade.ticker, action, entry, exit_price, pnl_usdt, pnl_pct,
            )
            
            # Broadcast to dashboard so UI updates immediately
            asyncio.create_task(broadcast_to_dashboard("trade_closed", {
                "id": str(trade.id),
                "ticker": trade.ticker,
                "pnl_usdt": pnl_usdt,
                "is_paper": True
            }))
            
    except Exception as e:
        logger.error("[PaperCloser] DB update failed for %s: %s", trade.ticker, e)
        return False

    # Telegram notification
    try:
        emoji = "🟢" if pnl_usdt >= 0 else "🔴"
        msg = (
            f"{emoji} <b>PAPER TRADE ЗАКРЫТА</b>\n\n"
            f"<b>Тикер:</b> #{trade.ticker} ({action})\n"
            f"<b>Вход:</b> ${entry:,.4f}\n"
            f"<b>Выход:</b> ${exit_price:,.4f}\n"
            f"<b>PnL:</b> ${pnl_usdt:+,.2f} ({pnl_pct:+.2f}%)\n"
            f"<b>Размер:</b> ${trade.size_usdt:,.2f}\n\n"
            f"<b>Причина:</b> {exit_reason}\n\n"
            f"#PAPER_CLOSE #{trade.ticker}"
        )
        await send_telegram_message(msg, parse_mode="HTML")
        # Email backup notification
        asyncio.create_task(send_email(
            subject=f"Trade Closed: {trade.ticker} {action} {pnl_usdt:+.2f} USDT",
            body=(
                f"{emoji} PAPER TRADE ЗАКРЫТА\n\n"
                f"Тикер: {trade.ticker} ({action})\n"
                f"Вход: ${entry:,.4f}\n"
                f"Выход: ${exit_price:,.4f}\n"
                f"PnL: ${pnl_usdt:+,.2f} ({pnl_pct:+.2f}%)\n"
                f"Размер: ${trade.size_usdt:,.2f}\n\n"
                f"Причина: {exit_reason}"
            )
        ))
    except Exception as e:
        logger.warning("[PaperCloser] Telegram alert failed: %s", e)

    return True


# ---------------------------------------------------------------------------
# Orphan detector
# ---------------------------------------------------------------------------

async def detect_orphan_trades() -> list[str]:
    """
    Find PaperTrades that have been OPEN for more than 24 hours
    without any SL/TP set. These are 'orphans' that will never close.
    Returns list of ticker names for logging.
    """
    orphans = []
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade)
                .where(PaperTrade.status == "OPEN")
            )
            open_trades = result.scalars().all()

            now = datetime.now(timezone.utc)
            for trade in open_trades:
                # Check if trade has no SL and no TP (will never auto-close)
                if (trade.stop_loss == 0 or trade.stop_loss is None) and \
                   (trade.take_profit == 0 or trade.take_profit is None):
                    orphans.append(f"{trade.ticker}({trade.action})")

                # Check if trade has been open for more than 48 hours
                if trade.created_at:
                    created = trade.created_at.replace(tzinfo=timezone.utc) if trade.created_at.tzinfo is None else trade.created_at
                    age_hours = (now - created).total_seconds() / 3600
                    if age_hours > 48:
                        orphans.append(f"{trade.ticker}({trade.action}, {age_hours:.0f}h old)")

    except Exception as e:
        logger.error("[PaperCloser] Orphan detection failed: %s", e)

    return orphans


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def paper_trade_closer_loop() -> None:
    """
    Main background loop. Runs every POLL_INTERVAL seconds.
    For each OPEN PaperTrade, checks current price against SL/TP.
    """
    logger.info("[PaperCloser] Starting paper trade closer loop (interval=%ds)...", POLL_INTERVAL)

    cycle_count = 0

    while True:
        try:
            cycle_count += 1

            # 1. Fetch all open paper trades
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PaperTrade).where(PaperTrade.status == "OPEN")
                )
                open_trades = result.scalars().all()

            if not open_trades:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            logger.info("[PaperCloser] Cycle #%d: Checking %d open paper trades...", cycle_count, len(open_trades))

            # 2. Fetch prices for all unique tickers
            unique_tickers = list(set(t.ticker for t in open_trades))
            prices = {}
            for ticker in unique_tickers:
                try:
                    price = await _exchange.get_price(ticker)
                    if price > 0:
                        prices[ticker] = price
                except Exception as e:
                    logger.warning("[PaperCloser] Price fetch failed for %s: %s", ticker, e)

            # 3. Check each trade
            closed_count = 0
            for trade in open_trades:
                price = prices.get(trade.ticker, 0.0)
                if price > 0:
                    was_closed = await _check_and_close_trade(trade, price)
                    if was_closed:
                        closed_count += 1

            if closed_count > 0:
                logger.info("[PaperCloser] Closed %d/%d trades this cycle.", closed_count, len(open_trades))

            # 4. Orphan detection (every 10 cycles = ~5 minutes)
            if cycle_count % 10 == 0:
                orphans = await detect_orphan_trades()
                if orphans:
                    logger.warning("[PaperCloser] ⚠️ Orphan trades detected: %s", ", ".join(orphans))

        except Exception as e:
            logger.error("[PaperCloser] Loop error: %s", e, exc_info=True)

        await asyncio.sleep(POLL_INTERVAL)
