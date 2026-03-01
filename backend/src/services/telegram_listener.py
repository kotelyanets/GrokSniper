"""
telegram_listener.py
--------------------
Interactive Telegram Command Center.
Listens for commands and updates global state.
"""

import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from sqlalchemy import select
from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade, PaperTrade
import backend.src.config as config
from backend.src.services.ws_manager import cancel_all_watchers
from backend.src.services.exchange import CryptoExchange

logger = logging.getLogger("telegram_listener")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    menu = (
        "🤖 <b>GrokSniper AI Command Center</b>\n\n"
        "Доступные команды:\n"
        "/status - Текущий статус бота и статистика\n"
        "/pause - Приостановить торговлю\n"
        "/resume - Возобновить торговлю\n"
        "/panic - 🚨 KILL SWITCH: Закрыть все и остановить"
    )
    await update.message.reply_html(menu)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    open_trades_count = 0
    open_paper_count = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
        open_trades_count = len(result.scalars().all())
        result_paper = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
        open_paper_count = len(result_paper.scalars().all())
        
    state_str = "⏸️ PAUSED" if config.TRADING_PAUSED else "▶️ RUNNING"
    msg = (
        f"📊 <b>Статус Бота</b>\n\n"
        f"Состояние: {state_str}\n"
        f"Открыто сделок (Real): {open_trades_count}\n"
        f"Открыто сделок (Paper): {open_paper_count}"
    )
    await update.message.reply_html(msg)

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = True
    await update.message.reply_text("⏸️ Trading Engine Paused. No new positions will be opened.")
    logger.info("Trading paused via Telegram.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = False
    await update.message.reply_text("▶️ Trading Engine Resumed.")
    logger.info("Trading resumed via Telegram.")

async def panic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = True
    await update.message.reply_text("🚨 PANIC MODE ACTIVATED. Parsing open positions to close...")
    logger.critical("PANIC MODE triggered via Telegram.")
    
    _exchange = CryptoExchange()
    closed_count = 0
    paper_count = 0
    
    try:
        async with AsyncSessionLocal() as session:
            # Close Paper Trades
            result_paper = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
            for pt in result_paper.scalars().all():
                pt.status = "CLOSED"
                paper_count += 1
                
            # Close Real Trades
            result_real = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
            real_trades = result_real.scalars().all()
            for t in real_trades:
                try:
                    amount = float(t.amount)
                    close_action = "SELL" if t.side in ("LONG", None) else "BUY"
                    order = await _exchange.place_order(ticker=t.ticker, action=close_action, amount=amount)
                    if order["status"] == "success":
                        t.is_closed = True
                        closed_count += 1
                except Exception as e:
                    logger.error(f"Panic close failed for {t.ticker}: {e}")
                    
            await session.commit()
            
        await update.message.reply_text(f"✅ Panic execution completed.\nClosed {closed_count} real trades and {paper_count} paper trades.")
        # Attempt to clean up watchers
        await cancel_all_watchers()
    except Exception as e:
        logger.error(f"Panic sequence encountered an error: {e}")
        await update.message.reply_text("⚠️ Panic encountered an error.")

def get_telegram_app() -> Application | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Listener disabled.")
        return None
        
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("panic", panic_command))
    return app

async def start_telegram_listener(app: Application):
    """Bootstraps the bot polling inside a running asyncio event loop."""
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram Command Center is active.")

async def stop_telegram_listener(app: Application):
    """Graceful shutdown for Telegram polling."""
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
