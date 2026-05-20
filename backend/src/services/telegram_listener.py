"""
telegram_listener.py
--------------------
Interactive Telegram Command Center.
Listens for commands, text messages, and voice messages.

Commands:
  /status      — System status overview
  /positions   — Manage open positions (Paper + Real)
  /pnl         — Realized PnL, win rate, equity summary
  /balance     — Portfolio balance breakdown
  /adaptation  — AI learning / adaptation score
  /board       — Board of Directors deep analysis
  /pause       — Pause trading
  /resume      — Resume trading
  /panic       — Emergency close ALL positions
  /help        — List all commands
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
    if not _ALLOWED_ID:
        logger.warning("ALLOWED_TELEGRAM_ID not configured — denying access by default.")
        return False  # No restriction configured — deny all for safety
    user = update.effective_user
    return user and str(user.id) == _ALLOWED_ID

def _is_paper_mode() -> bool:
    """Check if we're in paper/dry-run mode."""
    return (
        os.getenv("DRY_RUN", "False").lower() == "true" or
        os.getenv("PAPER_TRADE", "False").lower() == "true"
    )

async def _send_long_text(message, text: str, parse_mode=None):
    """Send text, splitting into chunks if it exceeds Telegram's 4096 char limit."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await message.reply_text(text, parse_mode=parse_mode)
        return
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
        await message.reply_text(chunk, parse_mode=parse_mode)

async def _reply(update, text, parse_mode="HTML", reply_markup=None):
    """Helper to reply to either a callback query or a regular message."""
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDS REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════
async def setup_commands(app: Application):
    commands = [
        BotCommand("status", "📊 Текущий статус бота"),
        BotCommand("positions", "💼 Управление позициями"),
        BotCommand("pnl", "💰 PnL и статистика"),
        BotCommand("balance", "💵 Баланс портфеля"),
        BotCommand("adaptation", "🧠 Уровень адаптации ИИ"),
        BotCommand("board", "🏛️ Анализ Board of Directors"),
        BotCommand("settings", "⚙️ Настройки бота"),
        BotCommand("history", "📜 Последние сделки"),
        BotCommand("metrics", "📈 Метрики капитала"),
        BotCommand("analyze", "🔎 Анaлиз монеты (напр. /analyze BTC)"),
        BotCommand("pause", "⏸️ Приостановить торговлю"),
        BotCommand("resume", "▶️ Возобновить торговлю"),
        BotCommand("panic", "🚨 Закрыть ВСЕ позиции"),
        BotCommand("help", "ℹ️ Список команд"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands menu registered in Telegram.")


# ═══════════════════════════════════════════════════════════════════════════════
# /start & /help
# ═══════════════════════════════════════════════════════════════════════════════
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    menu = (
        "🤖 <b>GrokSniper AI Command Center</b>\n\n"
        "Доступные команды:\n"
        "🔹 /status — 📊 Статус системы\n"
        "🔹 /positions — 💼 Управление позициями\n"
        "🔹 /pnl — 💰 PnL и винрейт\n"
        "🔹 /balance — 💵 Баланс портфеля\n"
        "🔹 /metrics — 📈 Метрики капитала и рисков\n"
        "🔹 /history — 📜 Последние закрытые сделки\n"
        "🔹 /analyze [BTC] — 🔎 Быстрый ИИ анализ монеты\n"
        "🔹 /adaptation — 🧠 Адаптация ИИ\n"
        "🔹 /board — 🏛️ Board of Directors\n"
        "🔹 /settings — ⚙️ Настройки бота\n"
        "🔹 /pause — ⏸️ Приостановить\n"
        "🔹 /resume — ▶️ Возобновить\n"
        "🔹 /panic — 🚨 Kill Switch\n\n"
        "💬 Или просто напишите / отправьте голосовое — ИИ ответит."
    )
    await _reply(update, menu)


# ═══════════════════════════════════════════════════════════════════════════════
# /status
# ═══════════════════════════════════════════════════════════════════════════════
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
        open_trades_count = len(result.scalars().all())
        result_paper = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
        open_paper_count = len(result_paper.scalars().all())
        
    state_str = "⏸️ <b>НА ПАУЗЕ</b>" if config.TRADING_PAUSED else "▶️ <b>РАБОТАЕТ</b>"
    mode_str = "📝 Paper Trading" if _is_paper_mode() else "🔴 LIVE Trading"
    
    try:
        is_live = not _is_paper_mode()
        _exchange = CryptoExchange()
        balance_data = await _exchange.get_balance()
        if is_live:
            total_balance = float(balance_data.get("total_usdt", 0.0))
        else:
            initial_equity = float(os.getenv("INITIAL_EQUITY", "1000"))
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                row = await session.execute(
                    text("SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_trades WHERE status = 'CLOSED'")
                )
                realized_pnl = float(row.scalar())
            total_balance = initial_equity + realized_pnl
    except Exception as e:
        logger.error(f"Status command balance fetch failed: {e}")
        total_balance = 0.0
    
    msg = (
        f"📊 <b>СТАТУС СИСТЕМЫ</b>\n\n"
        f"⚙️ <b>Состояние:</b> {state_str}\n"
        f"🏷️ <b>Режим:</b> {mode_str}\n"
        f"💰 <b>Баланс:</b> ${total_balance:,.2f}\n"
        f"📈 <b>Открыто (Real):</b> {open_trades_count}\n"
        f"📝 <b>Открыто (Paper):</b> {open_paper_count}"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Возобновить", callback_data="btn_resume") if config.TRADING_PAUSED else InlineKeyboardButton("⏸️ Пауза", callback_data="btn_pause"),
            InlineKeyboardButton("💼 Позиции", callback_data="btn_positions")
        ],
        [
            InlineKeyboardButton("💰 PnL", callback_data="btn_pnl"),
            InlineKeyboardButton("🧠 Адаптация", callback_data="btn_adaptation")
        ],
        [InlineKeyboardButton("🔄 Обновить", callback_data="btn_status")]
    ]
    await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))


# ═══════════════════════════════════════════════════════════════════════════════
# /positions — Shows BOTH Paper + Real open positions
# ═══════════════════════════════════════════════════════════════════════════════
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with AsyncSessionLocal() as session:
        # Get open PaperTrades
        paper_result = await session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN"))
        open_paper = paper_result.scalars().all()
        # Get open Real Trades
        real_result = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
        open_real = real_result.scalars().all()
    
    if not open_paper and not open_real:
        msg = "💼 <b>УПРАВЛЕНИЕ ПОЗИЦИЯМИ</b>\n\n✅ Нет открытых позиций."
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="btn_positions")]]
        await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    msg = "💼 <b>УПРАВЛЕНИЕ ПОЗИЦИЯМИ</b>\nВыберите позицию для закрытия:\n"
    keyboard = []
    
    # Paper positions
    for t in open_paper:
        side_emoji = "🟢" if t.action == "BUY" else "🔴"
        size = f"${float(t.size_usdt or 0):.0f}" if t.size_usdt else ""
        btn_text = f"❌ {side_emoji} {t.ticker} {size} [Paper]"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"closepaper_{t.id}")])
    
    # Real positions
    for t in open_real:
        side_emoji = "🟢" if t.side == "LONG" else "🔴"
        btn_text = f"❌ {side_emoji} {t.ticker} [Real]"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"closereal_{t.id}")])
        
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="btn_positions")])
    await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))


# ═══════════════════════════════════════════════════════════════════════════════
# Close Trade Callbacks — handles both Paper and Real
# ═══════════════════════════════════════════════════════════════════════════════
async def close_paper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    trade_id = query.data.split("_", 1)[1]  # Fix: UUID not int
    await query.answer()
    
    _exchange = CryptoExchange()
    try:
        async with AsyncSessionLocal() as session:
            import uuid as uuid_lib
            result = await session.execute(select(PaperTrade).where(PaperTrade.id == uuid_lib.UUID(trade_id), PaperTrade.status == "OPEN"))
            pt = result.scalar_one_or_none()
            if not pt:
                await query.edit_message_text("⚠️ Позиция не найдена (возможно, уже закрыта).")
                return
            
            # Get current price for preview
            try:
                price_data = await _exchange.fetch_ticker(pt.ticker)
                current_price = float(price_data.get('last', pt.entry_price))
            except Exception:
                current_price = float(pt.entry_price)
            
            entry = float(pt.entry_price)
            amount = float(pt.size_usdt or 0) / entry if entry > 0 else 0
            if pt.action == "LONG":
                pnl_usdt = (current_price - entry) * amount
            else:
                pnl_usdt = (entry - current_price) * amount
            
            sign = "+" if pnl_usdt >= 0 else ""
            emoji = "📈" if pnl_usdt >= 0 else "📉"
            
            # Confirmation step
            msg = (
                f"⚠️ <b>Закрыть {pt.ticker} [{pt.action}]?</b>\n\n"
                f"📥 Вход: ${entry:.4f}\n"
                f"📊 Текущая цена: ${current_price:.4f}\n"
                f"{emoji} Нереализованный PnL: <b>{sign}{pnl_usdt:.2f} USDT</b>\n\n"
                f"Подтвердите закрытие позиции:"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Да, закрыть", callback_data=f"confirm_paper_{trade_id}"),
                 InlineKeyboardButton("❌ Отмена", callback_data="btn_positions")]
            ]
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        logger.error(f"Paper close preview failed for {trade_id}: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")


async def confirm_paper_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actually closes the paper trade after user confirmation."""
    query = update.callback_query
    trade_id = query.data.split("_", 2)[2]  # confirm_paper_<uuid>
    await query.answer("Закрываю...")
    
    _exchange = CryptoExchange()
    try:
        async with AsyncSessionLocal() as session:
            import uuid as uuid_lib
            result = await session.execute(select(PaperTrade).where(PaperTrade.id == uuid_lib.UUID(trade_id), PaperTrade.status == "OPEN"))
            pt = result.scalar_one_or_none()
            if not pt:
                await query.edit_message_text("⚠️ Позиция уже закрыта.")
                return
            
            try:
                price_data = await _exchange.fetch_ticker(pt.ticker)
                current_price = float(price_data.get('last', pt.entry_price))
            except Exception:
                current_price = float(pt.entry_price)
            
            entry = float(pt.entry_price)
            amount = float(pt.size_usdt or 0) / entry if entry > 0 else 0
            pnl_usdt = (current_price - entry) * amount if pt.action == "LONG" else (entry - current_price) * amount
            
            pt.exit_price = current_price
            pt.pnl_usdt = pnl_usdt
            pt.status = "CLOSED"
            await session.commit()
            
            sign = "+" if pnl_usdt >= 0 else ""
            emoji = "✅" if pnl_usdt >= 0 else "❌"
            msg = (
                f"{emoji} <b>Paper позиция {pt.ticker} закрыта</b>\n\n"
                f"📥 Вход: ${entry:.4f}\n"
                f"📤 Выход: ${current_price:.4f}\n"
                f"💰 PnL: <b>{sign}{pnl_usdt:.2f} USDT</b>\n"
                f"📝 Причина: {(pt.ai_reasoning or 'N/A')[:100]}"
            )
            await query.edit_message_text(msg, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Paper confirm close failed for {trade_id}: {e}")
        await query.edit_message_text(f"⚠️ Ошибка при закрытии: {e}")


async def close_real_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    trade_id = query.data.split("_", 1)[1]  # Fix: UUID not int
    await query.answer()
    
    _exchange = CryptoExchange()
    try:
        async with AsyncSessionLocal() as session:
            import uuid as uuid_lib
            result = await session.execute(select(Trade).where(Trade.id == uuid_lib.UUID(trade_id), Trade.is_closed == False))
            t = result.scalar_one_or_none()
            if not t:
                await query.edit_message_text("⚠️ Позиция не найдена (возможно, уже закрыта).")
                return
            
            # Get current price for preview
            try:
                price_data = await _exchange.fetch_ticker(t.ticker)
                current_price = float(price_data.get('last', t.price))
            except Exception:
                current_price = float(t.price)
            
            entry = float(t.price)
            amount = float(t.amount)
            pnl_usdt = (current_price - entry) * amount if (t.side or "LONG") == "LONG" else (entry - current_price) * amount
            sign = "+" if pnl_usdt >= 0 else ""
            emoji = "📈" if pnl_usdt >= 0 else "📉"
            
            msg = (
                f"⚠️ <b>Закрыть {t.ticker} [Real]?</b>\n\n"
                f"📥 Вход: ${entry:.4f}\n"
                f"📊 Текущая цена: ${current_price:.4f}\n"
                f"{emoji} Нереализованный PnL: <b>{sign}{pnl_usdt:.2f} USDT</b>\n\n"
                f"Подтвердите закрытие позиции:"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Да, закрыть", callback_data=f"confirm_real_{trade_id}"),
                 InlineKeyboardButton("❌ Отмена", callback_data="btn_positions")]
            ]
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        logger.error(f"Real close preview failed for {trade_id}: {e}")
        await query.edit_message_text(f"⚠️ Ошибка при просмотре: {e}")


async def confirm_real_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actually closes the real trade after user confirmation."""
    query = update.callback_query
    trade_id = query.data.split("_", 2)[2]  # confirm_real_<uuid>
    await query.answer("Закрываю...")
    
    _exchange = CryptoExchange()
    try:
        async with AsyncSessionLocal() as session:
            import uuid as uuid_lib
            result = await session.execute(select(Trade).where(Trade.id == uuid_lib.UUID(trade_id), Trade.is_closed == False))
            t = result.scalar_one_or_none()
            if not t:
                await query.edit_message_text("⚠️ Позиция уже закрыта.")
                return
            
            amount = float(t.amount)
            close_action = "SELL" if (t.side or "LONG") == "LONG" else "BUY"
            
            if _is_paper_mode():
                try:
                    price_data = await _exchange.fetch_ticker(t.ticker)
                    current_price = float(price_data.get('last', t.price))
                except Exception:
                    current_price = float(t.price)
                    
                entry = float(t.price)
                pnl_usdt = (current_price - entry) * amount if close_action == "SELL" else (entry - current_price) * amount
                t.is_closed = True
                await session.commit()
                
                sign = "+" if pnl_usdt >= 0 else ""
                await query.edit_message_text(
                    f"✅ [PAPER] Позиция {t.ticker} закрыта.\n"
                    f"Цена: ${current_price:.4f}\nPnL: {sign}{pnl_usdt:.2f} USDT"
                )
            else:
                order = await _exchange.place_order(ticker=t.ticker, action=close_action, amount=amount)
                if order["status"] == "success":
                    t.is_closed = True
                    await session.commit()
                    await query.edit_message_text(f"✅ Позиция {t.ticker} успешно закрыта на бирже.")
                else:
                    await query.edit_message_text(f"❌ Ошибка биржи при закрытии {t.ticker}: {order}")
                    
    except Exception as e:
        logger.error(f"Real confirm close failed for {trade_id}: {e}")
        await query.edit_message_text(f"⚠️ Ошибка при закрытии: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# /pnl — Show realized PnL and win rate  
# ═══════════════════════════════════════════════════════════════════════════════
async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        is_live = not _is_paper_mode()
        async with AsyncSessionLocal() as session:
            if is_live:
                from sqlalchemy import text
                result = await session.execute(
                    text("""
                        SELECT b.ticker, (s.price * s.amount) - (b.price * b.amount) as pnl
                        FROM trades b
                        JOIN trades s ON s.parent_id = b.id
                        WHERE b.action = 'BUY'
                          AND s.action = 'SELL'
                          AND s.status IN ('filled', 'completed', 'success')
                        ORDER BY s.created_at DESC
                    """)
                )
                rows = result.fetchall()
                class LiveClosedTrade:
                    def __init__(self, ticker, pnl):
                        self.ticker = ticker
                        self.pnl_usdt = pnl
                trades = [LiveClosedTrade(row[0], float(row[1])) for row in rows]
            else:
                result = await session.execute(
                    select(PaperTrade).where(PaperTrade.status == "CLOSED").order_by(PaperTrade.created_at.desc())
                )
                trades = result.scalars().all()
        
        if not trades:
            await _reply(update, "💰 <b>PNL ОТЧЁТ</b>\n\nНет закрытых сделок.")
            return
        
        total_pnl = sum(float(t.pnl_usdt or 0) for t in trades)
        wins = sum(1 for t in trades if t.pnl_usdt and t.pnl_usdt > 0)
        losses = sum(1 for t in trades if t.pnl_usdt and t.pnl_usdt <= 0)
        win_rate = wins / len(trades) * 100 if trades else 0
        
        # Best and worst trades
        best = max(trades, key=lambda t: float(t.pnl_usdt or 0))
        worst = min(trades, key=lambda t: float(t.pnl_usdt or 0))
        
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        sign = "+" if total_pnl >= 0 else ""
        
        # Recent 5 trades
        recent_lines = []
        for t in trades[:5]:
            p = float(t.pnl_usdt or 0)
            s = "+" if p >= 0 else ""
            e = "✅" if p > 0 else "❌" if p < 0 else "➖"
            recent_lines.append(f"  {e} {t.ticker}: {s}{p:.2f} USDT")
        
        msg = (
            f"{pnl_emoji} <b>PNL ОТЧЁТ</b>\n\n"
            f"📊 <b>Всего сделок:</b> {len(trades)}\n"
            f"✅ <b>Побед:</b> {wins}\n"
            f"❌ <b>Поражений:</b> {losses}\n"
            f"🎯 <b>Win Rate:</b> {win_rate:.1f}%\n\n"
            f"💰 <b>Общий PnL:</b> {sign}{total_pnl:.2f} USDT\n"
            f"🏆 <b>Лучшая:</b> {best.ticker} +{float(best.pnl_usdt or 0):.2f}\n"
            f"💀 <b>Худшая:</b> {worst.ticker} {float(worst.pnl_usdt or 0):.2f}\n\n"
            f"📋 <b>Последние 5 сделок:</b>\n" + "\n".join(recent_lines)
        )
        
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="btn_pnl")]]
        await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
    except Exception as e:
        logger.error(f"PnL command error: {e}")
        await _reply(update, f"⚠️ Ошибка: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# /balance — Portfolio balance
# ═══════════════════════════════════════════════════════════════════════════════
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        initial_equity = float(os.getenv("INITIAL_EQUITY", "1000"))
        is_live = not _is_paper_mode()
        
        _exchange = CryptoExchange()
        balance_data = await _exchange.get_balance()
        holdings = balance_data.get("holdings", [])
        
        async with AsyncSessionLocal() as session:
            if is_live:
                from sqlalchemy import text
                realised_result = await session.execute(
                    text("""
                        SELECT COALESCE(
                            SUM(s.price * s.amount) - SUM(b.price * b.amount), 0
                        )
                        FROM trades b
                        JOIN trades s ON s.parent_id = b.id
                        WHERE b.action = 'BUY'
                          AND s.action = 'SELL'
                          AND s.status IN ('filled', 'completed', 'success')
                    """)
                )
                realized_pnl = float(realised_result.scalar() or 0.0)
                if realized_pnl == 0.0:
                    trades_count = (await session.execute(text("SELECT count(*) FROM trades"))).scalar() or 0
                    if trades_count > 0:
                        paper_pnl_result = await session.execute(
                            text("SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_trades WHERE status = 'CLOSED'")
                        )
                        realized_pnl = float(paper_pnl_result.scalar() or 0.0)
                
                result_real = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
                open_count = len(result_real.scalars().all())
                
                total_balance = float(balance_data.get("total_usdt", 0.0))
                available = float(balance_data.get("USDT", 0.0))
                invested = max(0.0, total_balance - available)
                
                # Dynamic initial equity for LIVE mode
                initial_equity = max(0.0, total_balance - realized_pnl)
            else:
                from sqlalchemy import text
                row = await session.execute(
                    text("SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_trades WHERE status = 'CLOSED'")
                )
                realized_pnl = float(row.scalar())
                
                row2 = await session.execute(
                    text("SELECT COALESCE(SUM(size_usdt), 0), COUNT(*) FROM paper_trades WHERE status = 'OPEN'")
                )
                invested, open_count = row2.fetchone()
                invested = float(invested)
                
                total_balance = initial_equity + realized_pnl
                available = total_balance - invested
        
        growth_pct = (realized_pnl / initial_equity * 100) if initial_equity > 0 else 0
        sign = "+" if realized_pnl >= 0 else ""
        emoji = "📈" if realized_pnl >= 0 else "📉"
        
        mode_prefix = "🔴 LIVE" if is_live else "📝 PAPER"
        
        msg = (
            f"💵 <b>БАЛАНС ПОРТФЕЛЯ ({mode_prefix})</b>\n\n"
            f"💰 <b>Общий баланс:</b> ${total_balance:,.2f}\n"
            f"🏦 <b>Начальный капитал:</b> ${initial_equity:,.2f}\n"
            f"{emoji} <b>Реализованный PnL:</b> {sign}${realized_pnl:,.2f}\n"
            f"📊 <b>Рост:</b> {sign}{growth_pct:.1f}%\n\n"
            f"📌 <b>В позициях:</b> ${invested:,.2f} ({open_count} шт.)\n"
            f"💵 <b>Свободно:</b> ${available:,.2f}"
        )
        
        if holdings and is_live:
            msg += "\n\n💼 <b>Текущие холдинги:</b>\n"
            for h in holdings:
                coin = h.get("coin", "")
                amt = float(h.get("amount", 0.0))
                val = float(h.get("value_usdt", 0.0))
                msg += f"  • {coin}: {amt:,.4f} (${val:,.2f})\n"
                
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="btn_balance")]]
        await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
    except Exception as e:
        logger.error(f"Balance command error: {e}")
        await _reply(update, f"⚠️ Ошибка: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# /adaptation — AI learning score
# ═══════════════════════════════════════════════════════════════════════════════
async def adaptation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from backend.src.services.memory_manager import get_adaptation_score
        data = await get_adaptation_score()
        
        score = data["score"]
        label = data["label"]
        wr = data["win_rate"]
        total = data["total_trades"]
        details = data.get("details", {})
        
        # Build progress bar
        filled = int(score / 5)  # 20 chars total
        bar = "█" * filled + "░" * (20 - filled)
        
        # Color emoji based on score
        if score >= 80:
            status_emoji = "🟢"
        elif score >= 55:
            status_emoji = "🔵"
        elif score >= 25:
            status_emoji = "🟡"
        else:
            status_emoji = "⚪"
        
        msg = (
            f"🧠 <b>АДАПТАЦИЯ ИИ</b>\n\n"
            f"{status_emoji} <b>Статус:</b> {label}\n"
            f"📊 <b>Оценка:</b> {score}/100\n"
            f"[{bar}]\n\n"
            f"🎯 <b>Win Rate:</b> {wr:.1f}%\n"
            f"📈 <b>Всего сделок:</b> {total}\n\n"
            f"<b>Компоненты оценки:</b>\n"
            f"  🎯 Win Rate: {details.get('win_rate_pts', 0):.0f}/40 pts\n"
            f"  📊 Стабильность: {details.get('consistency_pts', 0):.0f}/30 pts\n"
            f"  📈 Тренд обучения: {details.get('trend_pts', 0):.0f}/20 pts\n"
            f"  🌐 Диверсификация: {details.get('diversity_pts', 0):.0f}/10 pts\n\n"
            f"💡 <i>Бот учится на каждой сделке и адаптирует стратегию автоматически.</i>"
        )
        
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="btn_adaptation")]]
        await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))
        
    except Exception as e:
        logger.error(f"Adaptation command error: {e}")
        await _reply(update, f"⚠️ Ошибка: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# /pause & /resume
# ═══════════════════════════════════════════════════════════════════════════════
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = True
    if update.callback_query:
        await update.callback_query.answer("Пауза активирована")
        await status_command(update, context)
    else:
        await update.message.reply_html("⏸️ <b>Система на паузе.</b> Новые позиции открываться не будут.")
    logger.info("Trading paused via Telegram.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config.TRADING_PAUSED = False
    if update.callback_query:
        await update.callback_query.answer("Система возобновлена")
        await status_command(update, context)
    else:
        await update.message.reply_html("▶️ <b>Система возобновлена.</b> Торговля продолжается.")
    logger.info("Trading resumed via Telegram.")


# ═══════════════════════════════════════════════════════════════════════════════
# /board — Board of Directors analysis
# ═══════════════════════════════════════════════════════════════════════════════
async def board_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = "🏛️ <i>The Board of Directors is assembling to analyze the shadow logs. Please wait...</i>"
    if update.callback_query:
        await update.callback_query.message.reply_html(msg)
    else:
        await update.message.reply_html(msg)
        
    try:
        result = await get_board_decision()
        target = update.callback_query.message if update.callback_query else update.message
        await _send_long_text(target, result)
    except Exception as e:
        logger.error(f"Error in /board command: {e}")
        err_msg = f"🚨 Board error: {e}"
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text(err_msg)


# ═══════════════════════════════════════════════════════════════════════════════
# /panic — Emergency close ALL positions
# ═══════════════════════════════════════════════════════════════════════════════
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
            result_real = await session.execute(select(Trade).where(Trade.is_closed == False, Trade.action == "BUY"))
            real_trades = result_real.scalars().all()
            for t in real_trades:
                try:
                    if _is_paper_mode():
                        t.is_closed = True
                        closed_count += 1
                    else:
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
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_html(final_msg)
        cancel_all_watchers()
    except Exception as e:
        logger.error(f"Panic sequence error: {e}")
        err_msg = "⚠️ <b>Сбой во время ликвидации (Panic).</b> Проверьте логи!"
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_html(err_msg)


# ═══════════════════════════════════════════════════════════════════════════════
# Inline Button Router 
# ═══════════════════════════════════════════════════════════════════════════════
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    
    if data.startswith("closepaper_"):
        await close_paper_callback(update, context)
    elif data.startswith("closereal_"):
        await close_real_callback(update, context)
    elif data.startswith("confirm_paper_"):
        await confirm_paper_close(update, context)
    elif data.startswith("confirm_real_"):
        await confirm_real_close(update, context)
    elif data == "btn_status":
        await query.answer()
        await status_command(update, context)
    elif data == "btn_positions":
        await query.answer()
        await positions_command(update, context)
    elif data == "btn_pnl":
        await query.answer()
        await pnl_command(update, context)
    elif data == "btn_balance":
        await query.answer()
        await balance_command(update, context)
    elif data == "btn_adaptation":
        await query.answer()
        await adaptation_command(update, context)
    elif data == "btn_settings":
        await query.answer()
        await settings_command(update, context)
    elif data == "btn_conf_down":
        await handle_conf_change(update, -5)
    elif data == "btn_conf_up":
        await handle_conf_change(update, 5)
    elif data == "btn_pause":
        await pause_command(update, context)
    elif data == "btn_resume":
        await resume_command(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# AI Text & Voice Handlers
# ═══════════════════════════════════════════════════════════════════════════════
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await update.message.reply_text("🔒 Access Denied.")
        return
    
    user_id = update.effective_user.id
    user_text = update.message.text
    logger.info(f"AI chat from {user_id}: {user_text[:80]}...")
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
    if not _is_authorized(update):
        await update.message.reply_text("🔒 Access Denied.")
        return
    
    user_id = update.effective_user.id
    logger.info(f"Voice message from {user_id}")
    await update.message.reply_text("🎙️ Обрабатываю голосовое сообщение...")
    
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        voice_bytes = await file.download_as_bytearray()
        
        transcribed_text = await transcribe_voice(bytes(voice_bytes))
        
        if transcribed_text.startswith("❌"):
            await update.message.reply_text(transcribed_text)
            return
        
        await update.message.reply_text(f"📝 Распознано: {transcribed_text}")
        await update.message.chat.send_action("typing")
        response = await ai_chat(user_id, transcribed_text)
        if not response:
            response = "🤖 Голос распознан, но я не смог сгенерировать ответ."
        await _send_long_text(update.message, response)
        
    except Exception as e:
        logger.error(f"AI voice handler error: {e}")
        await update.message.reply_text(f"🚨 Ошибка обработки голоса: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Enhanced Trade Notification — Called by the engine when a trade is opened/closed
# ═══════════════════════════════════════════════════════════════════════════════
def format_trade_open_alert(ticker: str, action: str, price: float, size_usdt: float,
                            confidence: int, regime: str, reasoning: str,
                            sl: float = 0, tp: float = 0) -> str:
    """Format a rich trade open notification with AI reasoning."""
    side_emoji = "🟢 LONG" if action in ("BUY", "LONG") else "🔴 SHORT"
    
    # Confidence bar
    conf_filled = int(confidence / 10)
    conf_bar = "█" * conf_filled + "░" * (10 - conf_filled)
    
    msg = (
        f"🔔 <b>НОВАЯ СДЕЛКА</b>\n\n"
        f"{side_emoji} <b>{ticker}</b>\n\n"
        f"💰 <b>Размер:</b> ${size_usdt:.2f}\n"
        f"📍 <b>Цена входа:</b> ${price:.4f}\n"
    )
    
    if sl > 0:
        msg += f"🛡️ <b>Stop Loss:</b> ${sl:.4f}\n"
    if tp > 0:
        msg += f"🎯 <b>Take Profit:</b> ${tp:.4f}\n"
    
    msg += (
        f"\n📊 <b>Режим рынка:</b> {regime}\n"
        f"🎯 <b>Уверенность:</b> {confidence}% [{conf_bar}]\n\n"
        f"🤖 <b>Почему ИИ открыл:</b>\n"
        f"<i>{reasoning[:300]}</i>"
    )
    
    return msg


def format_trade_close_alert(ticker: str, action: str, entry_price: float,
                             exit_price: float, pnl_usdt: float,
                             reasoning: str = "") -> str:
    """Format a rich trade close notification with PnL and lesson learned."""
    pnl_emoji = "✅" if pnl_usdt >= 0 else "❌"
    sign = "+" if pnl_usdt >= 0 else ""
    side_emoji = "🟢" if action in ("BUY", "LONG") else "🔴"
    
    # PnL percentage
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    if action in ("SELL", "SHORT"):
        pnl_pct = -pnl_pct
    
    msg = (
        f"{pnl_emoji} <b>СДЕЛКА ЗАКРЫТА</b>\n\n"
        f"{side_emoji} <b>{ticker}</b>\n\n"
        f"📥 <b>Вход:</b> ${entry_price:.4f}\n"
        f"📤 <b>Выход:</b> ${exit_price:.4f}\n"
        f"💰 <b>PnL:</b> {sign}{pnl_usdt:.2f} USDT ({sign}{pnl_pct:.2f}%)\n"
    )
    
    if reasoning:
        msg += f"\n🤖 <b>Причина входа:</b>\n<i>{reasoning[:200]}</i>"
    
    return msg


# ═══════════════════════════════════════════════════════════════════════════════
# /settings
# ═══════════════════════════════════════════════════════════════════════════════
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current_conf = config.CONFIDENCE_THRESHOLD_OVERRIDE or int(os.getenv("CONFIDENCE_THRESHOLD", "60"))
    
    msg = (
        f"⚙️ <b>НАСТРОЙКИ БОТА</b>\n\n"
        f"🎯 <b>Порог уверенности ИИ:</b> {current_conf}%\n"
        f"<i>(Если ИИ предлагает сделку с уверенностью ниже порога, она блокируется)</i>\n\n"
        f"⏸️ <b>Торговля на паузе:</b> {'Да' if config.TRADING_PAUSED else 'Нет'}\n"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("➖ Порог", callback_data="btn_conf_down"),
            InlineKeyboardButton("➕ Порог", callback_data="btn_conf_up")
        ],
        [
            InlineKeyboardButton("▶️ Возобновить", callback_data="btn_resume") if config.TRADING_PAUSED else InlineKeyboardButton("⏸️ Пауза", callback_data="btn_pause")
        ],
        [InlineKeyboardButton("🔄 Обновить", callback_data="btn_settings")]
    ]
    await _reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_conf_change(update: Update, delta: int) -> None:
    current = config.CONFIDENCE_THRESHOLD_OVERRIDE or int(os.getenv("CONFIDENCE_THRESHOLD", "60"))
    new_val = max(10, min(100, current + delta))
    config.CONFIDENCE_THRESHOLD_OVERRIDE = new_val
    await update.callback_query.answer(f"Порог установлен на {new_val}%")
    await settings_command(update, None)

# ═══════════════════════════════════════════════════════════════════════════════
# /history
# ═══════════════════════════════════════════════════════════════════════════════
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["📜 <b>ПОСЛЕДНИЕ 10 СДЕЛОК</b>\n"]
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.status == "CLOSED").order_by(PaperTrade.created_at.desc()).limit(10)
            )
            trades = result.scalars().all()
            
            if not trades:
                lines.append("Нет закрытых сделок.")
            else:
                for idx, t in enumerate(trades, 1):
                    pnl = float(t.pnl_usdt or 0)
                    sign = "+" if pnl >= 0 else ""
                    emoji = "✅" if pnl > 0 else "❌"
                    lines.append(f"{idx}. {emoji} <b>{t.ticker} {t.action}</b>: {sign}{pnl:.2f} USDT")
                    
        await _reply(update, "\n".join(lines))
    except Exception as e:
        logger.error(f"History command error: {e}")
        await _reply(update, f"⚠️ Ошибка: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# /metrics
# ═══════════════════════════════════════════════════════════════════════════════
async def metrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from backend.src.services.capital_manager import global_capital_manager
    try:
        msg = (
            f"📈 <b>МЕТРИКИ КАПИТАЛА</b>\n\n"
            f"📊 <b>Max Portfolio Exposure:</b> 40%\n"
            f"💰 <b>Max Per Ticker:</b> 20%\n"
            f"📉 <b>Daily Drawdown Limit:</b> 15%\n\n"
            f"<i>Текущий статус защиты:</i> <b>Активен</b> 🛡️"
        )
        await _reply(update, msg)
    except Exception as e:
        logger.error(f"Metrics command error: {e}")
        await _reply(update, f"⚠️ Ошибка: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# /analyze <ticker>
# ═══════════════════════════════════════════════════════════════════════════════
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) == 0:
        await _reply(update, "⚠️ Вы должны указать тикер. Например: <code>/analyze BTC</code>")
        return
        
    ticker = context.args[0].upper().strip()
    await _reply(update, f"🔎 ИИ собирает графики и новости по <b>{ticker}</b>... Ожидайте.")
    
    try:
        response = await ai_chat(update.effective_user.id, f"Проанализируй текущую техническую и фундаментальную ситуацию по монете {ticker}. Стоит ли входить в Лонг или Шорт? Дай очень краткий ответ в 1-2 абзаца.")
        await _send_long_text(update.message, response)
    except Exception as e:
        logger.error(f"Analyze command error: {e}")
        await _reply(update, f"⚠️ Ошибка при анализе: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# App Builder & Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════
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
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("adaptation", adaptation_command))
    app.add_handler(CommandHandler("board", board_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("panic", panic_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("metrics", metrics_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
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
