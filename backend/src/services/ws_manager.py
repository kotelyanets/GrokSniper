"""
ws_manager.py
-------------
Phase 24 + Phase 30 – Real-Time WebSocket Position Manager.

Handles BOTH long and short positions:
  • LONG  – existing logic: track highest_price, exit on stop-loss / TP / trailing
  • SHORT – inverted logic: track lowest_price, exit on hard stop (+3%) / TP (-10%) / trailing bounce (+1.5% from trough)

Architecture:
  • One asyncio task per open trade, each connecting to:
      wss://stream.binance.com:9443/ws/<symbol>@trade
  • The main supervisor (`monitor_open_positions_ws`) rescans the DB every
    5 seconds to pick up newly opened positions and spawn their watchers.
  • When an exit condition fires the task:
      1. Executes a MARKET SELL (long) or MARKET BUY (short) via the exchange service.
      2. Marks the BUY trade as closed and writes a SELL record to the DB.
      3. Sends a Telegram notification.
      4. Cancels itself (the WebSocket connection closes naturally).
"""

import asyncio
import json
import logging
from decimal import Decimal

import websockets
from sqlalchemy import select

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message, send_exit_alert

logger = logging.getLogger("groksniper.ws")

# Shared exchange instance (re-uses the same one as server.py if possible,
# but we create a dedicated instance here so this module is self-contained).
_exchange = CryptoExchange()

# Track which trade IDs already have an active watcher task.
# Key: trade UUID  →  Value: asyncio.Task
_active_watchers: dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _binance_stream_url(ticker: str) -> str:
    """Returns the Binance trade-stream WebSocket URL for a ticker."""
    symbol = f"{ticker.lower()}usdt"
    return f"wss://stream.binance.com:9443/ws/{symbol}@trade"


async def _close_position(
    trade: Trade,
    exit_reason: str,
    exit_label: str,
    entry_price: float,
    highest_price: float,
    side: str = "LONG",
    lowest_price: float = 0.0,
) -> None:
    """
    Executes the MARKET SELL (long) or MARKET BUY (short), updates the DB,
    and sends the Telegram alert.
    Called once per trade when an exit condition fires.
    """
    # SHORT: BUY to close.  LONG: SELL to close.
    close_action = "BUY" if side == "SHORT" else "SELL"
    logger.info(f"[WS EXIT] {trade.ticker} ({side}) → {exit_label} → {close_action}")

    sell_order = await _exchange.place_order(
        ticker=trade.ticker,
        action=close_action,
        amount=0
    )

    if sell_order["status"] != "success":
        logger.error(f"[WS EXIT] {close_action} order failed for {trade.ticker}: {sell_order}")
        return

    close_price   = float(sell_order["price"])
    close_amount  = float(sell_order["amount"])

    if side == "SHORT":
        pnl_pct = ((entry_price - close_price) / entry_price) * 100
        pnl_usd = (entry_price - close_price) * close_amount
        reference_price = lowest_price
    else:
        pnl_pct = ((close_price - entry_price) / entry_price) * 100
        pnl_usd = (close_price - entry_price) * close_amount
        reference_price = highest_price

    # Persist to DB
    async with AsyncSessionLocal() as session:
        # Reload the trade inside this session (avoid detached-instance issues)
        result = await session.execute(select(Trade).where(Trade.id == trade.id))
        db_trade = result.scalar_one_or_none()
        if db_trade and not db_trade.is_closed:
            db_trade.is_closed = True

            s = Trade(
                ticker=trade.ticker,
                action="SELL" if side == "SHORT" else "SELL",
                amount=Decimal(str(close_amount)),
                price=Decimal(str(close_price)),
                status="success",
                is_closed=True,
                parent_id=trade.id,
                side=side,
            )
            session.add(s)
            await session.commit()
            logger.info(f"[WS EXIT] DB updated for {trade.ticker} ({side}) | PnL {pnl_pct:+.2f}%")

    # Telegram alert
    await send_exit_alert(
        ticker=trade.ticker,
        exit_label=exit_label,
        entry_price=entry_price,
        exit_price=close_price,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        side=side,
        reference_price=reference_price
    )


async def _watch_trade(trade_id: str) -> None:
    """
    Opens a persistent Binance trade-stream WebSocket for a single open position
    and evaluates exit conditions on every price tick.

    LONG exits (existing):
      1. Hard Stop-Loss  : price <= entry * 0.97
      2. Take Profit     : price >= entry * 1.10
      3. Delayed Trailing: (peak >= entry * 1.04) AND price <= peak * 0.985

    SHORT exits (Phase 30):
      1. Hard Stop-Loss  : price >= entry * 1.03  (3% loss)
      2. Take Profit     : price <= entry * 0.90  (10% profit)
      3. Delayed Trailing: (trough <= entry * 0.96) AND price >= trough * 1.015
    """
    # ── Load trade from DB ────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.id == trade_id))  # type: ignore[arg-type]
        trade = result.scalar_one_or_none()
        if trade is None or trade.is_closed:
            logger.info(f"[WS] Trade {trade_id} not found or already closed. Watcher exiting.")
            return

        ticker        = trade.ticker
        entry_price   = float(trade.price)
        side          = trade.side or "LONG"
        highest_price = float(trade.highest_price) if trade.highest_price else entry_price
        lowest_price  = float(trade.lowest_price) if trade.lowest_price else entry_price
        # ATR-based dynamic stop (Phase 32), falls back to hardcoded 3% for legacy trades
        if trade.stop_loss_price:
            dynamic_sl = float(trade.stop_loss_price)
        else:
            dynamic_sl = entry_price * 0.97 if side == "LONG" else entry_price * 1.03

    url = _binance_stream_url(ticker)
    logger.info(
        f"[WS] Connecting to {url} for {ticker} ({side}, entry=${entry_price:,.2f}, "
        f"SL=${dynamic_sl:,.2f})"
    )

    # Track whether we already sent the trailing-stop activation alert
    if side == "SHORT":
        trailing_activated = lowest_price <= entry_price * 0.96
    else:
        trailing_activated = highest_price >= entry_price * 1.04

    try:
        async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
            async for raw_msg in ws:
                try:
                    msg  = json.loads(raw_msg)
                    price = float(msg.get("p", 0))   # "p" = price in @trade stream
                    if price == 0:
                        continue
                except (json.JSONDecodeError, ValueError):
                    continue

                # ══════════════════════════════════════════════════════════
                # LONG PATH
                # ══════════════════════════════════════════════════════════
                if side == "LONG":
                    # ── Update running peak ───────────────────────────────
                    if price > highest_price:
                        highest_price = price
                        asyncio.create_task(_update_peak(trade_id, highest_price))

                    # ── Trailing Stop Activation Alert ────────────────────
                    if not trailing_activated and highest_price >= entry_price * 1.04:
                        trailing_activated = True
                        pnl_now = ((price - entry_price) / entry_price) * 100
                        trail_msg = (
                            f"🔒 <b>TRAILING STOP АКТИВИРОВАН</b>\n\n"
                            f"<b>Тикер:</b> #{ticker}\n"
                            f"<b>Цена входа:</b> ${entry_price:,.4f}\n"
                            f"<b>Текущая цена:</b> ${price:,.4f} ({pnl_now:+.2f}%)\n"
                            f"<b>Пик:</b> ${highest_price:,.4f}\n"
                            f"<b>Trail trigger:</b> ${highest_price * 0.985:,.4f}\n\n"
                            f"Позиция теперь защищена скользящим стопом (-1.5% от пика).\n"
                            f"Минимальная прибыль гарантирована! 🛡️"
                        )
                        asyncio.create_task(send_telegram_message(trail_msg))
                        logger.info(f"[WS] Trailing stop activated for {ticker} at ${price:,.4f}")

                    # ── EXIT CONDITIONS (priority order) ──────────────────
                    exit_reason: str | None = None
                    exit_label:  str       = ""

                    # 1. Hard Stop-Loss: ATR-based dynamic stop (replaces hardcoded -3%)
                    if price <= dynamic_sl:
                        sl_pct = ((entry_price - dynamic_sl) / entry_price) * 100
                        exit_reason = "hard_stop"
                        exit_label  = (
                            f"Dynamic Stop-Loss (ATR | entry ${entry_price:,.4f} → "
                            f"stop ${dynamic_sl:,.4f}, -{sl_pct:.1f}%)"
                        )

                    # 2. Fixed Take Profit: +10% from entry
                    elif price >= entry_price * 1.10:
                        exit_reason = "take_profit"
                        exit_label  = (
                            f"Take Profit (+10% | entry ${entry_price:,.4f} → "
                            f"target ${entry_price * 1.10:,.4f})"
                        )

                    # 3. Delayed Trailing Stop: activates only after +4% profit
                    elif highest_price >= entry_price * 1.04:
                        trailing_trigger = highest_price * 0.985
                        if price <= trailing_trigger:
                            exit_reason = "trailing_stop"
                            exit_label  = (
                                f"Delayed Trailing Stop (-1.5% from peak "
                                f"${highest_price:,.4f}, trigger=${trailing_trigger:,.4f})"
                            )

                    if exit_reason:
                        async with AsyncSessionLocal() as session:
                            res = await session.execute(
                                select(Trade).where(Trade.id == trade_id)  # type: ignore[arg-type]
                            )
                            db_trade = res.scalar_one_or_none()
                            if db_trade is None or db_trade.is_closed:
                                logger.info(f"[WS] {ticker} already closed externally — skipping.")
                                return

                        await _close_position(
                            trade=trade,
                            exit_reason=exit_reason,
                            exit_label=exit_label,
                            entry_price=entry_price,
                            highest_price=highest_price,
                            side="LONG",
                        )
                        return

                # ══════════════════════════════════════════════════════════
                # SHORT PATH (Phase 30)
                # ══════════════════════════════════════════════════════════
                else:
                    # ── Update running trough (lowest price) ──────────────
                    if price < lowest_price:
                        lowest_price = price
                        asyncio.create_task(_update_trough(trade_id, lowest_price))

                    # ── Trailing Stop Activation Alert (SHORT) ────────────
                    if not trailing_activated and lowest_price <= entry_price * 0.96:
                        trailing_activated = True
                        pnl_now = ((entry_price - price) / entry_price) * 100
                        trail_msg = (
                            f"🔒 <b>SHORT TRAILING STOP АКТИВИРОВАН</b>\n\n"
                            f"<b>Тикер:</b> #{ticker}\n"
                            f"<b>Цена входа:</b> ${entry_price:,.4f}\n"
                            f"<b>Текущая цена:</b> ${price:,.4f} ({pnl_now:+.2f}%)\n"
                            f"<b>Минимум:</b> ${lowest_price:,.4f}\n"
                            f"<b>Trail trigger:</b> ${lowest_price * 1.015:,.4f}\n\n"
                            f"SHORT защищён trailing stop (+1.5% от минимума).\n"
                            f"Прибыль зафиксирована! 🛡️"
                        )
                        asyncio.create_task(send_telegram_message(trail_msg))
                        logger.info(f"[WS] SHORT trailing stop activated for {ticker} at ${price:,.4f}")

                    # ── SHORT EXIT CONDITIONS (priority order) ────────────
                    exit_reason: str | None = None
                    exit_label:  str       = ""

                    # 1. Hard Stop-Loss: ATR-based dynamic stop (replaces hardcoded +3%)
                    if price >= dynamic_sl:
                        sl_pct = ((dynamic_sl - entry_price) / entry_price) * 100
                        exit_reason = "hard_stop"
                        exit_label  = (
                            f"SHORT Dynamic Stop (ATR | entry ${entry_price:,.4f} → "
                            f"stop ${dynamic_sl:,.4f}, +{sl_pct:.1f}%)"
                        )

                    # 2. Fixed Take Profit: -10% from entry (SHORT wins when price drops)
                    elif price <= entry_price * 0.90:
                        exit_reason = "take_profit"
                        exit_label  = (
                            f"SHORT Take Profit (-10% | entry ${entry_price:,.4f} → "
                            f"target ${entry_price * 0.90:,.4f})"
                        )

                    # 3. Delayed Trailing Stop: activates after -4% profit for SHORT
                    elif lowest_price <= entry_price * 0.96:
                        trailing_trigger = lowest_price * 1.015
                        if price >= trailing_trigger:
                            exit_reason = "trailing_stop"
                            exit_label  = (
                                f"SHORT Trailing Stop (+1.5% from trough "
                                f"${lowest_price:,.4f}, trigger=${trailing_trigger:,.4f})"
                            )

                    if exit_reason:
                        async with AsyncSessionLocal() as session:
                            res = await session.execute(
                                select(Trade).where(Trade.id == trade_id)  # type: ignore[arg-type]
                            )
                            db_trade = res.scalar_one_or_none()
                            if db_trade is None or db_trade.is_closed:
                                logger.info(f"[WS] {ticker} SHORT already closed externally — skipping.")
                                return

                        await _close_position(
                            trade=trade,
                            exit_reason=exit_reason,
                            exit_label=exit_label,
                            entry_price=entry_price,
                            highest_price=highest_price,
                            side="SHORT",
                            lowest_price=lowest_price,
                        )
                        return  # BUY to close executed — task done

    except asyncio.CancelledError:
        logger.info(f"[WS] Watcher for {ticker} ({trade_id}) cancelled.")
    except Exception as e:
        logger.error(f"[WS] Unexpected error watching {ticker}: {e}")
    finally:
        _active_watchers.pop(str(trade_id), None)


async def _update_peak(trade_id: str, new_peak: float) -> None:
    """Persists a new highest_price to the DB (fire-and-forget)."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade).where(Trade.id == trade_id))  # type: ignore[arg-type]
            db_trade = result.scalar_one_or_none()
            if db_trade and not db_trade.is_closed:
                db_trade.highest_price = Decimal(str(new_peak))
                await session.commit()
    except Exception as e:
        logger.warning(f"[WS] Peak update failed for {trade_id}: {e}")


async def _update_trough(trade_id: str, new_trough: float) -> None:
    """Persists a new lowest_price to the DB (fire-and-forget). Used for SHORT trailing stops."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade).where(Trade.id == trade_id))  # type: ignore[arg-type]
            db_trade = result.scalar_one_or_none()
            if db_trade and not db_trade.is_closed:
                db_trade.lowest_price = new_trough
                await session.commit()
    except Exception as e:
        logger.warning(f"[WS] Trough update failed for {trade_id}: {e}")


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

async def monitor_open_positions_ws() -> None:
    """
    Supervisor task (runs forever):
    - Every 5 seconds, queries the DB for open BUY trades (LONG and SHORT).
    - Spawns a `_watch_trade` task for each trade that doesn't already
      have an active watcher.
    - Cleans up finished/cancelled tasks from the registry.
    """
    logger.info("[WS Supervisor] Starting real-time position monitor...")

    while True:
        try:
            async with AsyncSessionLocal() as session:
                stmt   = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")
                result = await session.execute(stmt)
                open_trades = result.scalars().all()

            # Prune completed tasks from the registry
            dead = [tid for tid, task in _active_watchers.items() if task.done()]
            for tid in dead:
                _active_watchers.pop(tid, None)

            # Spawn watchers for newly opened positions
            for trade in open_trades:
                tid = str(trade.id)
                if tid not in _active_watchers:
                    side_label = trade.side or "LONG"
                    logger.info(f"[WS Supervisor] Spawning watcher for {trade.ticker} ({side_label}, id={tid})")
                    task = asyncio.create_task(
                        _watch_trade(tid),
                        name=f"ws_watcher_{trade.ticker}_{tid[:8]}",
                    )
                    _active_watchers[tid] = task

        except Exception as e:
            logger.error(f"[WS Supervisor] Error: {e}")

        await asyncio.sleep(5)


def cancel_all_watchers() -> None:
    """
    Gracefully cancels all active watcher tasks.
    Call this during server shutdown.
    """
    logger.info(f"[WS Supervisor] Cancelling {len(_active_watchers)} active watcher(s)...")
    for task in _active_watchers.values():
        task.cancel()
    _active_watchers.clear()
