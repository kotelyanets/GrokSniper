"""
telegram_listener.py
--------------------
Interactive Telegram Command Center.
Listens for commands, text messages, and voice messages.
"""

import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import Conflict
from sqlalchemy import select
from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade, PaperTrade
import backend.src.config as config
from backend.src.services.ws_manager import cancel_all_watchers
from backend.src.services.exchange import CryptoExchange
from backend.src.agents.board_of_directors import get_board_decision
from backend.src.agents.telegram_assistant import chat as ai_chat, transcribe_voice

logger = logging.getLogger("telegram_listener")

# ---------------------------------------------------------------------------
# Security — only the authorized user can interact with the AI assistant
# ---------------------------------------------------------------------------
_ALLOWED_ID = os.getenv("ALLOWED_TELEGRAM_ID", "").strip()

def _is_authorized(update: Update) -> bool:
    """Check if the message sender is the authorized user."""
    if not _ALLOWED_ID:
        logger.warning("ALLOWED_TELEGRAM_ID not configured — denying access by default.")
        return False  # No restriction configured — deny all for safety
    user = update.effective_user
    if user and str(user.id) == _ALLOWED_ID:
        return True
    return False

async def _send_long_text(message, text: str):
    """Send text, splitting into chunks if it exceeds Telegram's 4096 char limit."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await message.reply_text(text)
        return
    # Split on newlines where possible
    chunks = []
    while len(text) > MAX_LEN:
        split_at = text.rfind("\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    for chunk in chunks:
        await message.reply_text(chunk)

async def setup_commands(app: Application):
    """Register the bot commands in the Telegram UI menu."""
    commands = [
        BotCommand("status", "📊 Текущий статус бота"),
        BotCommand("positions", "💼 Управление позициями"),
        BotCommand("board", "🏛️ Запросить анализ Board of Directors"),
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
        "Доступные команды:\n"
        "🔹 /status — 📊 Текущий статус бота\n"
        "🔹 /positions — 💼 Управление открытыми позициями\n"
        "🔹 /board — 🏛️ Запросить анализ Board of Directors\n"
        "🔹 /pause — ⏸️ Приостановить торговлю\n"
        "🔹 /resume — ▶️ Возобновить торговлю\n"
        "🔹 /panic — 🚨 Закрыть ВСЕ позиции\n\n"
        "💬 Или просто напишите / отправьте голосовое — ИИ ответит."
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
            
            # --- BUG 2 FIX: Paper Trading Bypass ---
            is_paper = os.getenv("PAPER_TRADE", "False").lower() == "true"
            
            if is_paper:
                # Bypass real exchange execution
                try:
                    price_data = await _exchange.fetch_ticker(t.ticker)
                    current_price = price_data.get('last', t.entry_price)
                except Exception:
                    current_price = t.entry_price
                    
                if close_action == "SELL":  # Closing a LONG
                    pnl_usdt = (current_price - t.entry_price) * amount
                else:                       # Closing a SHORT
                    pnl_usdt = (t.entry_price - current_price) * amount
                    
                t.exit_price = current_price
                t.pnl_usdt = pnl_usdt
                t.is_closed = True
                await session.commit()
                
                sign = "+" if pnl_usdt >= 0 else ""
                await query.edit_message_text(f"📝 [PAPER] Позиция {t.ticker} закрыта.\nЦена: {current_price:.4f}\nPnL: {sign}{pnl_usdt:.2f} USDT")
            
            else:
                # Live Exchange Execution
                order = await _exchange.place_order(ticker=t.ticker, action=close_action, amount=amount)
                
                if order["status"] == "success":
                    t.is_closed = True
                    # Let the main sync loop catch the exit price + pnl later
                    await session.commit()
                    await query.edit_message_text(f"✅ Позиция {t.ticker} успешно закрыта на бирже.")
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
                
            # Close Real/Simulated Trades
            is_paper = os.getenv("PAPER_TRADE", "False").lower() == "true"
            result_real = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
            real_trades = result_real.scalars().all()
            for t in real_trades:
                try:
                    if is_paper:
                        # --- PAPER MODE: No real exchange call ---
                        t.is_closed = True
                        closed_count += 1
                    else:
                        # --- LIVE MODE: Execute on exchange ---
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
        cancel_all_watchers()
    except Exception as e:
        logger.error(f"Panic sequence encountered an error: {e}")
        err_msg = "⚠️ <b>Сбой во время ликвидации (Panic).</b> Проверьте логи сервера!"
        if update.callback_query:
            await update.callback_query.message.reply_html(err_msg)
        else:
            await update.message.reply_html(err_msg)

async def board_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = "🏛️ <i>The Board of Directors is assembling to analyze the shadow logs. Please wait...</i>"
    if update.callback_query:
        await update.callback_query.message.reply_html(msg)
    else:
        await update.message.reply_html(msg)
        
    try:
        result = await get_board_decision()
        
        # Output raw text to avoid unescaped characters breaking HTML parsing
        if update.callback_query:
            await update.callback_query.message.reply_text(result)
        else:
            await update.message.reply_text(result)
            
    except Exception as e:
        logger.error(f"Error in /board command: {e}")
        err_msg = f"🚨 Ошибка при получении ответа от Board of Directors: {e}"
        if update.callback_query:
            await update.callback_query.message.reply_text(err_msg)
        else:
            await update.message.reply_text(err_msg)

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

# ---------------------------------------------------------------------------
# Text & Voice Message Handlers (AI Assistant)
# ---------------------------------------------------------------------------
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages — route to the AI assistant."""
    if not _is_authorized(update):
        await update.message.reply_text("🔒 Access Denied.")
        return
    
    user_id = update.effective_user.id
    user_text = update.message.text
    logger.info(f"AI chat from {user_id}: {user_text[:80]}...")
    
    # Show typing indicator
    await update.message.chat.send_action("typing")
    
    try:
        response = await ai_chat(user_id, user_text)
        if not response:
            response = "🤖 Извини, я не смог сформулировать ответ. Попробуй еще раз!"
        await _send_long_text(update.message, response)
    except Exception as e:
        logger.error(f"AI text handler error: {e}")
        await update.message.reply_text(f"🚨 Ошибка ИИ-ассистента: {e}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages — transcribe via Whisper then route to AI."""
    if not _is_authorized(update):
        await update.message.reply_text("🔒 Access Denied.")
        return
    
    user_id = update.effective_user.id
    logger.info(f"Voice message from {user_id}")
    
    await update.message.reply_text("🎙️ Обрабатываю голосовое сообщение...")
    
    try:
        # Download the voice file
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        voice_bytes = await file.download_as_bytearray()
        
        # Transcribe
        transcribed_text = await transcribe_voice(bytes(voice_bytes))
        
        if transcribed_text.startswith("❌"):
            await update.message.reply_text(transcribed_text)
            return
        
        # Show what was heard
        await update.message.reply_text(f"📝 Распознано: {transcribed_text}")
        
        # Send typing indicator and process through AI
        await update.message.chat.send_action("typing")
        response = await ai_chat(user_id, transcribed_text)
        if not response:
            response = "🤖 Голос распознан, но я не смог сгенерировать ответ."
        await _send_long_text(update.message, response)
        
    except Exception as e:
        logger.error(f"AI voice handler error: {e}")
        await update.message.reply_text(f"🚨 Ошибка обработки голоса: {e}")


def get_telegram_app() -> Application | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Listener disabled.")
        return None
        
    app = Application.builder().token(token).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("board", board_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("panic", panic_command))
    app.add_handler(CallbackQueryHandler(button_router))
    
    # AI Assistant handlers (text + voice)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    
    return app

async def start_telegram_listener(app: Application):
    """Bootstraps the bot polling inside a running asyncio event loop."""
    await app.initialize()
    await app.start()
    await setup_commands(app)
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram Command Center is active.")
            break
        except Conflict as e:
            if attempt < max_retries - 1:
                logger.warning(f"Telegram polling conflict. Retrying in 2 seconds... ({attempt+1}/{max_retries})")
                await asyncio.sleep(2.0)
            else:
                logger.error("Failed to start Telegram polling after multiple retries due to Conflict.")
                raise e

async def stop_telegram_listener(app: Application):
    """Graceful shutdown for Telegram polling."""
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
