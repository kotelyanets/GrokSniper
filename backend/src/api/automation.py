"""
automation.py
-------------
GrokSniper 24/7 background tasks.

Contains:
  - _fetch_live_micro_candles()  — live 5m/15m OHLCV features for ML
  - _portfolio_summary_loop()    — sends a Telegram summary every 4 hours
  - _automation_loop()           — main scan loop (news + Pure AI Engine)

These are started as asyncio tasks by the lifespan handler in server.py.
"""

import asyncio
import logging
import os

from sqlalchemy import select, text

import backend.src.config as config
from backend.src.api.state import WATCHLIST, update_bot_state
from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import Trade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.rss_scraper import fetch_latest_news
from backend.src.services.telegram_bot import send_telegram_message

logger = logging.getLogger("groksniper.api")

_exchange = CryptoExchange()


# ---------------------------------------------------------------------------
# Live micro-candle fetch for ML predictions (Phase 32)
# ---------------------------------------------------------------------------
async def _fetch_live_micro_candles(ticker: str) -> dict | None:
    """
    Fetches the last 1 hour of 5m and 15m candles for a ticker from Binance.
    Returns {"5m_volatility": float, "15m_volume_spike": float} or None.
    """
    import ccxt.async_support as ccxt
    import time

    if ticker in ("NONE", "UNKNOWN", ""):
        return None

    symbol   = f"{ticker}/USDT"
    now_ms   = int(time.time() * 1000)
    since_ms = now_ms - 3_600_000  # 1 hour ago

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        ohlcv_5m  = await exchange.fetch_ohlcv(symbol, "5m",  since=since_ms, limit=12)
        ohlcv_15m = await exchange.fetch_ohlcv(symbol, "15m", since=since_ms, limit=4)

        if not ohlcv_5m or not ohlcv_15m:
            return None

        # 5m_volatility: average (high - low)
        volatilities = [float(c[2]) - float(c[3]) for c in ohlcv_5m]
        avg_5m_vol   = sum(volatilities) / len(volatilities) if volatilities else 0.0

        # 15m_volume_spike: max volume / mean volume
        volumes_15m = [float(c[5]) for c in ohlcv_15m]
        mean_v  = sum(volumes_15m) / len(volumes_15m) if volumes_15m else 1.0
        max_v   = max(volumes_15m) if volumes_15m else 0.0
        vol_spike = round(max_v / mean_v, 4) if mean_v > 0 else 1.0

        return {
            "5m_volatility":    round(avg_5m_vol, 6),
            "15m_volume_spike": vol_spike,
        }
    except Exception as e:
        logger.debug(f"Live micro-candles fetch failed for {ticker}: {e}")
        return None
    finally:
        await exchange.close()


# ---------------------------------------------------------------------------
# Periodic Portfolio Summary (runs every 4 hours)
# ---------------------------------------------------------------------------
async def _portfolio_summary_loop() -> None:
    """Sends a Telegram portfolio summary every N hours (SUMMARY_INTERVAL_HOURS env)."""
    from datetime import datetime
    INTERVAL = int(os.getenv("SUMMARY_INTERVAL_HOURS", "4")) * 3600
    await asyncio.sleep(60)      # wait 1 min after startup for things to settle
    while True:
        try:
            balance_data = await _exchange.get_balance()
            total_usdt   = balance_data.get("total_usdt", 0.0)

            # Open positions from DB
            async with AsyncSessionLocal() as session:
                stmt   = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")
                result = await session.execute(stmt)
                open_trades = result.scalars().all()

            positions_text = ""
            for t in open_trades:
                cur_price = await _exchange.get_price(t.ticker)
                entry     = float(t.price)
                pnl_pct   = ((cur_price - entry) / entry * 100) if entry > 0 else 0
                emoji     = "🟢" if pnl_pct >= 0 else "🔴"
                positions_text += f"  {emoji} {t.ticker}: ${cur_price:,.2f} (вход ${entry:,.2f}, {pnl_pct:+.1f}%)\n"

            if not positions_text:
                positions_text = "  Нет открытых позиций\n"

            async with AsyncSessionLocal() as session:
                trades_24h = (await session.execute(
                    text("SELECT count(*) FROM trades WHERE created_at > NOW() - INTERVAL '24 hours'")
                )).scalar() or 0

            msg = (
                f"📊 <b>СВОДКА ПОРТФЕЛЯ</b>\n\n"
                f"<b>Общий капитал:</b> ${total_usdt:,.2f}\n"
                f"<b>Сделок за 24ч:</b> {trades_24h}\n"
                f"<b>Открытые позиции:</b>\n{positions_text}\n"
                f"⏰ Следующая сводка через {INTERVAL // 3600}ч\n\n"
                f"#СВОДКА #ПОРТФЕЛЬ"
            )

            reply_markup = {
                "inline_keyboard": [[
                    {"text": "💼 Управление позициями", "callback_data": "btn_positions"},
                    {"text": "📊 Текущий статус",       "callback_data": "btn_status"},
                ]]
            }
            await send_telegram_message(msg, reply_markup=reply_markup)
            logger.info(f"[Summary] Periodic portfolio summary sent. Equity: ${total_usdt:,.2f}")

        except Exception as e:
            logger.error(f"[Summary] Error sending periodic summary: {e}")

        await asyncio.sleep(INTERVAL)


# ---------------------------------------------------------------------------
# Main 24/7 Automation Loop
# ---------------------------------------------------------------------------
async def _automation_loop() -> None:
    """
    24/7 background task:
    Fetches news and runs the Pure AI Engine once per SCAN_INTERVAL seconds.
    """
    logger.info("Starting GrokSniper Pure AI Automation Loop...")

    highest_equity    = 0.0
    reported_milestones: set[int] = set()
    MAJOR_MILESTONES  = [500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000]

    while True:
        try:
            if config.TRADING_PAUSED:
                update_bot_state(status="⏸️ Paused (Remote Kill Switch)")
                await asyncio.sleep(15)
                continue

            # Fetch news once per cycle
            update_bot_state(status="Fetching latest market news...")
            news_record = await fetch_latest_news()
            news_text   = news_record["text"] if news_record else ""

            # Run Pure AI Engine (Phase 8 Batch mode)
            update_bot_state(status="🧠 Running Pure AI Engine (Claude Sonnet)...")
            logger.info("Starting Pure AI Engine batch scan for all tickers.")

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers(latest_news=news_text)

            executed = [r["ticker"] for r in results if r.get("trade_placed")]
            held     = [r["ticker"] for r in results if r.get("action") == "HOLD"]
            skipped  = [r["ticker"] for r in results if not r.get("trade_placed") and r.get("action") != "HOLD"]
            logger.info(
                f"AI Engine Cycle Complete. "
                f"Executed: {len(executed)} | Held: {len(held)} | Skipped: {len(skipped)}"
            )
            if executed:
                logger.info(f"Executed trades for: {', '.join(executed)}")

            # Milestone & Equity Check
            try:
                balance_data   = await _exchange.get_balance()
                current_equity = balance_data.get("total_usdt", 0.0)
                if current_equity > highest_equity:
                    highest_equity = current_equity

                for milestone in MAJOR_MILESTONES:
                    if current_equity >= milestone and milestone not in reported_milestones:
                        reported_milestones.add(milestone)
                        logger.info(f"🏆 MILESTONE REACHED: {milestone}")
                        msg = (
                            f"🏆 <b>ДОСТИГНУТ РУБЕЖ!</b>\n\n"
                            f"Ваш общий капитал только что превысил <b>${milestone:,.2f}</b>!\n\n"
                            f"Рекомендуем обновить <code>RESERVE_USDT</code> в файле <code>.env</code>, "
                            f"чтобы зафиксировать прибыль.\n\n"
                            f"#MILESTONE #ПРИБЫЛЬ"
                        )
                        await send_telegram_message(msg)
            except Exception as e:
                logger.error(f"Milestone Check Error: {e}")

        except Exception as e:
            logger.error(f"Automation Loop Error: {e}", exc_info=True)

        update_bot_state(status="Idle (Waiting for next cycle...)")
        scan_interval = int(os.getenv("SCAN_INTERVAL", "900"))
        await asyncio.sleep(scan_interval)
