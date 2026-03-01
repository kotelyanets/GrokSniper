"""
telegram_bot.py
---------------
Telegram Notification Service for GrokSniper AI.
Phase 38: Institutional HTML Reporting (Russian Localization)
"""

import logging
import os
import httpx

logger = logging.getLogger(__name__)

def escape_html(text: str) -> str:
    """Escapes HTML special characters to prevent parsing errors in Telegram."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def send_telegram_message(text: str, parse_mode: str = "HTML", reply_markup: dict = None) -> None:
    """
    Sends a message to all Telegram chats configured in TELEGRAM_CHAT_ID.
    Defaults to HTML parse mode for Premium Institutional formatting.
    Accepts optional reply_markup dict for inline keyboards.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_str = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_ids_str:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing. Skipping notification.")
        return

    chat_ids = [cid.strip() for cid in chat_ids_str.split(",") if cid.strip()]
    if not chat_ids:
        logger.warning("No valid Telegram chat IDs found after splitting. Skipping.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    success_count = 0

    async with httpx.AsyncClient() as client:
        for chat_id in chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True  # Keep chat clean
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
                
            try:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to send Telegram message to {chat_id}: {e}")

    if success_count > 0:
        logger.info(f"Telegram: Message sent to {success_count} recipients.")

# Alias for backward compatibility
send_message = send_telegram_message


# ═══════════════════════════════════════════════════════════════════════════
# Institutional Templates (Phase 38)
# ═══════════════════════════════════════════════════════════════════════════

async def send_entry_alert(
    ticker: str, 
    action: str, 
    price: float, 
    size: float, 
    stop_loss: float, 
    confidence: int | float, 
    ai_reasoning: str,
    event_type: str = "СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ",
    is_ml_hype: bool = False
) -> None:
    """
    Sends a premium HTML-formatted entry alert in Russian.
    """
    direction_str = "🟢 LONG" if action.upper() == "BUY" else "🔴 SHORT"
    escaped_reasoning = escape_html(ai_reasoning)
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ticker.upper()}USDT"

    # For ML Hype trades, we label the source differently than standard CrewAI
    source_label = "ИИ-Модель (ML Hype)" if is_ml_hype else "ИИ-Совет (CrewAI)"

    msg = (
        f"🚨 <b>{event_type}</b> 🚨\n\n"
        f"🔹 <b>Монета:</b> #{ticker.upper()}\n"
        f"🧭 <b>Направление:</b> {direction_str}\n\n"
        f"🧠 <b>Вердикт {source_label}:</b>\n"
        f"• <b>Уверенность:</b> {confidence}%\n"
        f"• <b>Логика:</b> <i>{escaped_reasoning}</i>\n\n"
        f"⚙️ <b>Детали исполнения:</b>\n"
        f"• <b>Цена входа:</b> {price:,.4f} USDT\n"
        f"• <b>Объем сделки:</b> ${size:,.2f}\n"
        f"• <b>Динамический Стоп (ATR):</b> {stop_loss:,.4f} USDT\n\n"
        f"📊 <a href=\"{tv_link}\">Открыть график TradingView</a>\n\n"
        f"#{ticker.upper()} #{direction_str.replace('🟢 ', '').replace('🔴 ', '')} #ВХОД"
    )
    await send_telegram_message(msg)


async def send_exit_alert(
    ticker: str,
    exit_label: str,
    entry_price: float,
    exit_price: float,
    pnl_usd: float,
    pnl_pct: float,
    side: str,
    reference_price: float
) -> None:
    """
    Sends a premium HTML-formatted exit alert in Russian.
    """
    emoji = "💰" if pnl_pct > 0 else "📉"
    side_str = "LONG" if side.upper() == "LONG" else "SHORT"
    ref_label = "Пик (Peak)" if side.upper() == "LONG" else "Мин. (Trough)"
    
    escaped_label = escape_html(exit_label)
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ticker.upper()}USDT"

    msg = (
        f"{emoji} <b>ЗАКРЫТИЕ ПОЗИЦИИ ({side_str})</b>\n\n"
        f"🔹 <b>Монета:</b> #{ticker.upper()}\n"
        f"🛑 <b>Причина:</b> {escaped_label}\n\n"
        f"⚙️ <b>Итоги:</b>\n"
        f"• <b>Цена выхода:</b> {exit_price:,.4f} USDT\n"
        f"• <b>Цена входа:</b> {entry_price:,.4f} USDT\n"
        f"• <b>{ref_label}:</b> {reference_price:,.4f} USDT\n\n"
        f"💵 <b>Ожидаемый P&L:</b> <b>{pnl_pct:+.2f}%</b> (${pnl_usd:+.2f})\n\n"
        f"📊 <a href=\"{tv_link}\">Открыть график TradingView</a>\n\n"
        f"#{ticker.upper()} #{side_str} #ВЫХОД"
    )
    await send_telegram_message(msg)
