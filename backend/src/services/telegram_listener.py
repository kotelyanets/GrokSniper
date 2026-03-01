"""
telegram_listener.py
--------------------
Interactive Telegram Command Center.
Listens for commands and updates global state.
"""

import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from sqlalchemy import select
from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade, PaperTrade
import backend.src.config as config
from backend.src.services.ws_manager import cancel_all_watchers
from backend.src.services.exchange import CryptoExchange

logger = logging.getLogger("telegram_listener")

async def setup_commands(app: Application):
    """Register the bot commands in the Telegram UI menu."""
    commands = [
        BotCommand("status", "📊 Текущий статус бота"),
        BotCommand("positions", "💼 Управление позициями"),
        BotCommand("pause", "⏸️ Приостановить торговлю"),
        BotCommand("resume", "▶️ Возобновить торговлю"),
        BotCommand("panic", "🚨 Закрыть ВСЕ позиции (Kill Switch)"),
        BotCommand("help", "ℹ️ Список команд")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands menu registered in Telegram.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    menu = (
        "🤖 <b>GrokSniper AI Command Center</b>\n\n"
        "Доступные команды (выберите в меню слева от поля ввода):\n"
        "🔹 /status — 📊 Текущий статус бота\n"
        "🔹 /positions — 💼 Управление открытыми позициями\n"
        "🔹 /pause — ⏸️ Приостановить торговлю\n"
        "🔹 /resume — ▶️ Возобновить торговлю\n"
        "🔹 /panic — 🚨 Закрыть ВСЕ позиции и остановить бота"
    )
    if update.callback_query:
        await update.callback_query.message.reply_html(menu)
    else:
        await update.message.reply_html(menu)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    open_trades_count = 0
    open_paper_count = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
        open_trades_count = len(result.scalars().all())
        result_paper = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
        open_paper_count = len(result_paper.scalars().all())
        
    state_str = "⏸️ <b>НА ПАУЗЕ</b>" if config.TRADING_PAUSED else "▶️ <b>РАБОТАЕТ</b>"
    
    msg = (
        f"📊 <b>СТАТУС СИСТЕМЫ</b>\n\n"
        f"⚙️ <b>Состояние:</b> {state_str}\n"
        f"📈 <b>Открыто позиций (Real):</b> {open_trades_count}\n"
        f"📝 <b>Открыто позиций (Paper):</b> {open_paper_count}"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Возобновить", callback_data="btn_resume") if config.TRADING_PAUSED else InlineKeyboardButton("⏸️ Пауза", callback_data="btn_pause"),
            InlineKeyboardButton("💼 Позиции", callback_data="btn_positions")
        ],
        [InlineKeyboardButton("🔄 Обновить", callback_data="btn_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_html(msg, reply_markup=reply_markup)

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
        open_trades = result.scalars().all()
    
    if not open_trades:
        msg = "💼 <b>УПРАВЛЕНИЕ ПОЗИЦИЯМИ</b>\n\nНет открытых реальных позиций."
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="btn_positions")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_html(msg, reply_markup=reply_markup)
        return

    msg = "💼 <b>УПРАВЛЕНИЕ ПОЗИЦИЯМИ</b>\nВыберите активную позицию для закрытия:\n"
    keyboard = []
    
    for t in open_trades:
        side_emoji = "🟢" if t.side == "LONG" else "🔴"
        btn_text = f"❌ Закрыть {side_emoji} {t.ticker}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"close_{t.id}")])
        
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="btn_positions")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_html(msg, reply_markup=reply_markup)

async def close_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    trade_id = query.data.split("_")[1]
    
    await query.answer(f"Инициировано закрытие {trade_id}...")
    
    _exchange = CryptoExchange()
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade).where(Trade.id == trade_id, Trade.is_closed == False))
            t = result.scalar_one_or_none()
            if not t:
                await query.edit_message_text("⚠️ Не удалось найти позицию (возможно, уже закрыта).")
                return
                
            amount = float(t.amount)
            close_action = "SELL" if t.side in ("LONG", None) else "BUY"
            order = await _exchange.place_order(ticker=t.ticker, action=close_action, amount=amount)
            
            if order["status"] == "success":
                t.is_closed = True
                await session.commit()
                await query.edit_message_text(f"✅ Позиция {t.ticker} успешно закрыта вручную.")
            else:
                await query.edit_message_text(f"❌ Ошибка биржи при закрытии {t.ticker}: {order}")
    except Exception as e:
        logger.error(f"Manual close failed for {trade_id}: {e}")
        await query.edit_message_text("⚠️ Ошибка при закрытии позиции.")

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = True
    msg = "⏸️ <b>Система на паузе.</b> Новые позиции открываться не будут."
    if update.callback_query:
        await update.callback_query.answer("Пауза активирована")
        await status_command(update, context)
    else:
        await update.message.reply_html(msg)
    logger.info("Trading paused via Telegram.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = False
    msg = "▶️ <b>Система возобновлена.</b> Торговля продолжается."
    if update.callback_query:
        await update.callback_query.answer("Система возобновлена")
        await status_command(update, context)
    else:
        await update.message.reply_html(msg)
    logger.info("Trading resumed via Telegram.")

async def panic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = True
    msg = "🚨 <b>PANIC MODE ACTIVATED</b> 🚨\nЗакрываем все позиции..."
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_html(msg)
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
            
        final_msg = f"✅ <b>Panic Mode Завершен</b>\nЗакрыто: {closed_count} реальных и {paper_count} демо-сделок."
        if update.callback_query:
            await update.callback_query.message.reply_html(final_msg)
        else:
            await update.message.reply_html(final_msg)
        # Attempt to clean up watchers
        await cancel_all_watchers()
    except Exception as e:
        logger.error(f"Panic sequence encountered an error: {e}")
        err_msg = "⚠️ <b>Сбой во время ликвидации (Panic).</b> Проверьте логи сервера!"
        if update.callback_query:
            await update.callback_query.message.reply_html(err_msg)
        else:
            await update.message.reply_html(err_msg)

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes inline button presses to the corresponding functions."""
    query = update.callback_query
    
    if query.data.startswith("close_"):
        await close_trade_callback(update, context)
    elif query.data == "btn_status":
        await query.answer()
        await status_command(update, context)
    elif query.data == "btn_positions":
        await query.answer()
        await positions_command(update, context)
    elif query.data == "btn_pause":
        await pause_command(update, context)
    elif query.data == "btn_resume":
        await resume_command(update, context)

def get_telegram_app() -> Application | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Listener disabled.")
        return None
        
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("panic", panic_command))
    app.add_handler(CallbackQueryHandler(button_router))
    return app

async def start_telegram_listener(app: Application):
    """Bootstraps the bot polling inside a running asyncio event loop."""
    await app.initialize()
    await app.start()
    await setup_commands(app)
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram Command Center is active.")

async def stop_telegram_listener(app: Application):
    """Graceful shutdown for Telegram polling."""
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
