"""
server.py
---------
FastAPI server for GrokSniper AI.
Integrated with 24/7 background automation loop.
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text
from datetime import datetime
from uuid import UUID
from typing import Optional
import json

from backend.src.db.database import AsyncSessionLocal, Base, engine
from backend.src.db.models import NewsLog, Trade, PaperTrade, AgentDecisionLog
from backend.src.services.pre_filter import passes_pre_filter
PAPER_TRADE = os.getenv("PAPER_TRADE", "True").lower() == "true"
from backend.src.services.rss_scraper import fetch_latest_news
from backend.src.services.crew_analyzer import analyze_news
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message, send_entry_alert
from backend.src.ml.predictor import calibrate_score, predict_return
from backend.src.services.ws_manager import monitor_open_positions_ws, cancel_all_watchers
import backend.src.config as config
from backend.src.services.telegram_listener import get_telegram_app, start_telegram_listener, stop_telegram_listener



logger = logging.getLogger("groksniper.api")

# Shared instances
_exchange = CryptoExchange()

# ---------------------------------------------------------------------------
# Background Automation Loop
# ---------------------------------------------------------------------------
bot_state = {
    "status": "System Initialized",
    "last_action": "None",
    "started_at": datetime.utcnow().isoformat()
}

# ---------------------------------------------------------------------------
# Dashboard WebSocket Manager
# ---------------------------------------------------------------------------
class DashboardWSManager:
    """Manages all active WebSocket connections from the dashboard frontend."""
    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._clients.add(websocket)
        logger.info(f"[WS Dashboard] Client connected. Total: {len(self._clients)}")

    def disconnect(self, websocket: WebSocket):
        self._clients.discard(websocket)
        logger.info(f"[WS Dashboard] Client disconnected. Total: {len(self._clients)}")

    async def broadcast(self, message: dict):
        """Fire-and-forget broadcast to all connected dashboard clients."""
        if not self._clients:
            return
        dead: set[WebSocket] = set()
        payload = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

dashboard_ws_manager = DashboardWSManager()

async def broadcast_to_dashboard(event: str, data: dict):
    """Convenience wrapper — all broadcasts include a type field."""
    await dashboard_ws_manager.broadcast({"type": event, **data})

def update_bot_state(status: str = None, action: str = None):
    if status is not None:
        bot_state["status"] = status
    if action is not None:
        bot_state["last_action"] = action
    # Non-blocking push to connected dashboard clients
    asyncio.ensure_future(broadcast_to_dashboard("bot_state", bot_state.copy()))

WATCHLIST = ['BTC', 'ETH', 'SOL', 'DOGE', 'XRP']

# ---------------------------------------------------------------------------
# Periodic Portfolio Summary (runs every 4 hours)
# ---------------------------------------------------------------------------
async def _portfolio_summary_loop() -> None:
    """Sends a Telegram portfolio summary every 4 hours."""
    INTERVAL = int(os.getenv("SUMMARY_INTERVAL_HOURS", "4")) * 3600
    await asyncio.sleep(60)  # wait 1 min after startup to let things initialize
    while True:
        try:
            balance_data = await _exchange.get_balance()
            total_usdt = balance_data.get("total_usdt", 0.0)
            holdings = balance_data.get("holdings", [])

            # Open positions from DB
            async with AsyncSessionLocal() as session:
                stmt = select(Trade).where(Trade.is_closed == False, Trade.action == "BUY")
                result = await session.execute(stmt)
                open_trades = result.scalars().all()

            positions_text = ""
            for t in open_trades:
                cur_price = await _exchange.get_price(t.ticker)
                entry = float(t.price)
                pnl_pct = ((cur_price - entry) / entry * 100) if entry > 0 else 0
                emoji = "🟢" if pnl_pct >= 0 else "🔴"
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
                "inline_keyboard": [
                    [
                        {"text": "💼 Управление позициями", "callback_data": "btn_positions"},
                        {"text": "📊 Текущий статус", "callback_data": "btn_status"}
                    ]
                ]
            }
            
            await send_telegram_message(msg, reply_markup=reply_markup)
            logger.info(f"[Summary] Periodic portfolio summary sent. Equity: ${total_usdt:,.2f}")

        except Exception as e:
            logger.error(f"[Summary] Error sending periodic summary: {e}")

        await asyncio.sleep(INTERVAL)


# ---------------------------------------------------------------------------
# Live micro-candle fetch for ML predictions (Phase 32)
# ---------------------------------------------------------------------------
async def _fetch_live_micro_candles(ticker: str) -> dict | None:
    """
    Fetches the last 1 hour of 5m and 15m candles for a ticker from Binance.
    Returns {"5m_volatility": float, "15m_volume_spike": float} or None.
    Same computation as bootcamp's _fetch_micro_candles but uses "now" as reference.
    """
    import ccxt.async_support as ccxt
    import time

    if ticker in ("NONE", "UNKNOWN", ""):
        return None

    symbol = f"{ticker}/USDT"
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - 3_600_000  # 1 hour ago

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        ohlcv_5m  = await exchange.fetch_ohlcv(symbol, "5m", since=since_ms, limit=12)
        ohlcv_15m = await exchange.fetch_ohlcv(symbol, "15m", since=since_ms, limit=4)

        if not ohlcv_5m or not ohlcv_15m:
            return None

        # 5m_volatility: average (high - low)
        volatilities = [float(c[2]) - float(c[3]) for c in ohlcv_5m]
        avg_5m_vol = sum(volatilities) / len(volatilities) if volatilities else 0.0

        # 15m_volume_spike: max volume / mean volume
        volumes_15m = [float(c[5]) for c in ohlcv_15m]
        mean_v = sum(volumes_15m) / len(volumes_15m) if volumes_15m else 1.0
        max_v  = max(volumes_15m) if volumes_15m else 0.0
        vol_spike = round(max_v / mean_v, 4) if mean_v > 0 else 1.0

        return {
            "5m_volatility": round(avg_5m_vol, 6),
            "15m_volume_spike": vol_spike,
        }
    except Exception as e:
        logger.debug(f"Live micro-candles fetch failed for {ticker}: {e}")
        return None
    finally:
        await exchange.close()


def calculate_position_size(free_usdt: float, expected_return: float, atr: float, current_price: float) -> tuple[float, str]:
    """
    Dynamically sizes the trade based on ML Confidence (expected_return) and Market Volatility (ATR).
    Returns (usdt_to_spend, sizing_reason).
    """
    BASE_RISK = 0.05  # Base trade size is 5% of free balance
    
    # 1. ML Confidence Multiplier
    ml_mult = 1.0
    abs_return = abs(expected_return)
    if abs_return >= 0.01:
        # Scale from 1.0x (at 1% return) up to 2.5x (at >= 3% return)
        ml_mult = min(2.5, 1.0 + (abs_return - 0.01) * (1.5 / 0.02))
    
    # 2. Volatility Penalty (ATR % of Price)
    vol_penalty = 1.0
    if current_price > 0:
        atr_pct = atr / current_price
        if atr_pct > 0.04:
            vol_penalty = 0.5  # High volatility: halve size
        elif atr_pct > 0.02:
            # Scale from 1.0 (at 2% ATR) down to 0.5 (at 4% ATR)
            vol_penalty = 1.0 - ((atr_pct - 0.02) * (0.5 / 0.02))

    raw_size = free_usdt * BASE_RISK * ml_mult * vol_penalty
    
    # Constraints
    final_size = max(raw_size, 10.0) # Binance minimum $10
    final_size = min(final_size, free_usdt * 0.25) # Hard cap 25% of balance
    
    # Format reasoning string for Telegram
    conf_str = "High Conf" if ml_mult > 1.5 else "Norm Conf" if ml_mult >= 1.0 else "Low Conf"
    vol_str = "High Vol" if vol_penalty < 0.7 else "Norm Vol"
    reason = f"{conf_str}, {vol_str}"
    
    return final_size, reason


async def scan_charts_for_opportunities():
    """
    Elite Confluence TA Scanner with Multi-Timeframe (MTF) Alignment:

    4h Macro Gate:
      Bullish: 4h close > EMA_50  (macro trend is UP)
      Bearish: 4h close < EMA_50  (macro trend is DOWN)

    1h Micro Triggers (only if 4h gate passes):
      Bullish: Trend + MACD cross + RSI 40-65 + Body + Volume
      Bearish: Inverse trend + MACD bear cross + RSI 35-60

    ATR-Based Dynamic Stop Loss:
      stop_loss_distance = ATR(14) * 1.5
    """
    if config.TRADING_PAUSED:
        return

    try:

        for ticker in WATCHLIST:
            update_bot_state(status=f"[MTF TA Scanner] Scanning {ticker}...")

            # ── Pre-filter gate ──────────────────────────────────────────
            if not await passes_pre_filter(ticker):
                continue

            # ── Fetch BOTH timeframes ──────────────────────────────────────
            ta_data_1h = await _exchange.get_technical_indicators(ticker, '1h')
            ta_data_4h = await _exchange.get_technical_indicators(ticker, '4h')
            current_price = await _exchange.get_price(ticker)
            if current_price == 0:
                continue

            # ── 4h Macro Trend Evaluation ──────────────────────────────────
            close_4h   = ta_data_4h.get("close", 0.0)
            ema_50_4h  = ta_data_4h.get("ema_50", 0.0)
            macro_bullish = close_4h > ema_50_4h
            macro_bearish = close_4h < ema_50_4h

            logger.info(
                f"[4h MTF] {ticker} | close={close_4h:.2f} EMA50={ema_50_4h:.2f} "
                f"→ Macro={'BULLISH' if macro_bullish else 'BEARISH' if macro_bearish else 'NEUTRAL'}"
            )

            # ── 1h Indicators ──────────────────────────────────────────────
            ema_20          = ta_data_1h.get("ema_20", 0.0)
            ema_50          = ta_data_1h.get("ema_50", 0.0)
            macd_line       = ta_data_1h.get("macd_line", 0.0)
            macd_signal     = ta_data_1h.get("macd_signal", 0.0)
            prev_macd_line  = ta_data_1h.get("prev_macd_line", 0.0)
            prev_macd_signal= ta_data_1h.get("prev_macd_signal", 0.0)
            rsi             = ta_data_1h.get("rsi", 50.0)
            candle_open     = ta_data_1h.get("open", current_price)
            candle_high     = ta_data_1h.get("high", current_price)
            candle_low      = ta_data_1h.get("low", current_price)
            candle_close    = ta_data_1h.get("close", current_price)
            current_volume  = ta_data_1h.get("current_volume", 0.0)
            volume_sma_20   = ta_data_1h.get("volume_sma_20", 0.0)
            atr             = ta_data_1h.get("atr", 0.0)

            # ── Elite Confluence BUY Conditions (1h) ───────────────────────
            cond_trend   = candle_close > ema_50 and ema_20 > ema_50
            cond_macd    = macd_line > macd_signal and prev_macd_line <= prev_macd_signal
            cond_rsi     = 40 < rsi < 65
            candle_mid   = (candle_high + candle_low) / 2
            cond_body    = candle_close > candle_mid
            cond_vol     = volume_sma_20 > 0 and current_volume > (volume_sma_20 * 1.05)

            # MTF Gate: 1h bullish only fires if 4h macro is bullish
            passed_all = macro_bullish and cond_trend and cond_macd and cond_rsi and cond_body and cond_vol

            conditions = {
                "4h Macro": macro_bullish,
                "Trend": cond_trend,
                "MACD": cond_macd,
                "RSI": cond_rsi,
                "Body": cond_body,
                "Volume": cond_vol,
            }
            passed_count = sum(conditions.values())

            logger.info(
                f"[1h TA] {ticker} | 4hMacro:{macro_bullish} Trend:{cond_trend} MACD:{cond_macd} "
                f"RSI:{cond_rsi}({rsi:.1f}) Body:{cond_body} Vol:{cond_vol} ATR:{atr:.2f} → BUY={passed_all}"
            )

            # ── Watchlist Alert: 5 out of 6 passed ─────────────────────────
            if not passed_all and passed_count >= 5:
                watch_msg = (
                    f"👀 <b>WATCHLIST: #{ticker}</b>\n\n"
                    f"Прошёл <b>{passed_count}/6</b> фильтров MTF Confluence\n"
                    f"❌ Не прошёл: Возможный сбой фильтра\n\n"
                    f"<b>RSI:</b> {rsi:.1f} | <b>Цена:</b> ${current_price:,.2f}\n"
                    f"<b>EMA20:</b> {ema_20:.2f} | <b>EMA50:</b> {ema_50:.2f}\n"
                    f"<b>4h:</b> close={close_4h:.2f} EMA50={ema_50_4h:.2f}\n"
                    f"Объём: {current_volume/volume_sma_20:.2f}x SMA\n\n"
                    f"⚠️ Близок к сигналу на покупку — следите!\n\n"
                    f"#WATCHLIST #{ticker}"
                )
                await send_telegram_message(watch_msg)

            if passed_all:
                # ── ATR-Based Dynamic Stop Loss ────────────────────────────
                stop_loss_distance = atr * 1.5 if atr > 0 else current_price * 0.03
                stop_loss_price = current_price - stop_loss_distance

                logger.info(
                    f"[MTF TA Scanner] ALL elite filters + 4h macro passed for {ticker}! "
                    f"close={candle_close:.2f} EMA20={ema_20:.2f} EMA50={ema_50:.2f} "
                    f"RSI={rsi:.1f} Vol={current_volume/volume_sma_20:.2f}x SMA "
                    f"ATR={atr:.2f} SL=${stop_loss_price:.2f}"
                )

                # Fetch balance and size position
                free_usdt = await _exchange.get_free_balance('USDT')
                reserve_usdt  = float(os.getenv("RESERVE_USDT", "0.0"))
                effective_balance = max(0.0, free_usdt - reserve_usdt)

                usdt_to_spend, size_reason = calculate_position_size(
                    free_usdt=effective_balance, 
                    expected_return=0.02, # Neutral default for TA scanner
                    atr=atr, 
                    current_price=current_price
                )

                if usdt_to_spend < 10:
                    logger.warning(
                        f"[MTF TA Scanner] Insufficient capital for {ticker}. "
                        f"Available: {free_usdt:.2f}, Reserve: {reserve_usdt:.2f}, "
                        f"To Spend: {usdt_to_spend:.2f}."
                    )
                    continue

                amount_to_buy = usdt_to_spend / current_price
                logger.info(f"[MTF TA Scanner] Attempting to BUY {amount_to_buy:.6f} {ticker} for ~${usdt_to_spend:.2f} USDT")

                # ── Execution gate: LONG (Paper vs Real) ─────────────────
                if PAPER_TRADE:
                    try:
                        atr_pt = atr if atr > 0 else current_price * 0.01
                        sl_pt = current_price - atr_pt * 1.5
                        tp_pt = current_price + atr_pt * 3.0
                        async with AsyncSessionLocal() as session:
                            pt = PaperTrade(
                                ticker=ticker,
                                action="LONG",
                                entry_price=current_price,
                                size_usdt=usdt_to_spend,
                                stop_loss=sl_pt,
                                take_profit=tp_pt,
                                status="OPEN",
                                strategy_used="TA_SCANNER",
                            )
                            session.add(pt)
                            await session.commit()
                        update_bot_state(action=f"[PAPER] TA LONG {ticker} @ {current_price:.2f}")
                        logger.info(
                            f"[PAPER TRADE TA] {ticker} LONG "
                            f"@ {current_price} | SL={sl_pt:.2f} TP={tp_pt:.2f}"
                        )
                        ai_reasoning = f"MTF Confluence: 1h + 4h (RSI {rsi:.1f}, Vol {current_volume/volume_sma_20:.1f}x SMA, 4h Macro Bullish)"
                        await send_entry_alert(
                            ticker=f"[PAPER TRADE] {ticker}",
                            action="BUY",
                            price=current_price,
                            size=usdt_to_spend,
                            stop_loss=sl_pt,
                            confidence=85,
                            ai_reasoning=ai_reasoning,
                            is_ml_hype=False
                        )
                    except Exception as e:
                        logger.error(f"[PAPER TRADE TA] Failed to log paper trade: {e}")
                else:
                    order = await _exchange.place_order(ticker=ticker, action="BUY", amount=amount_to_buy)

                    if order["status"] == "success":
                        update_bot_state(action=f"[MTF TA] Bought {amount_to_buy:.4f} {ticker}")
                        async with AsyncSessionLocal() as session:
                            t = Trade(
                                ticker=ticker,
                                action="BUY",
                                amount=Decimal(str(order["amount"])),
                                price=Decimal(str(order["price"])),
                                highest_price=Decimal(str(order["price"])),
                                stop_loss_price=stop_loss_price,
                                position_size_usdt=usdt_to_spend,
                                status="success",
                                is_closed=False,
                                reason="mtf_ta_scanner"
                            )
                            session.add(t)
                            await session.commit()

                        # 5. Institutional Telegram Notification
                        ai_reasoning = f"MTF Confluence: 1h + 4h (RSI {rsi:.1f}, Vol {current_volume/volume_sma_20:.1f}x SMA, 4h Macro Bullish)"
                        await send_entry_alert(
                            ticker=ticker,
                            action="BUY",
                            price=order["price"],
                            size=usdt_to_spend,
                            stop_loss=stop_loss_price,
                            confidence=85,
                            ai_reasoning=ai_reasoning,
                            is_ml_hype=False
                        )

            # ── Elite Confluence SHORT (Bearish) Conditions ────────────────
            cond_bear_trend = candle_close < ema_50 and ema_20 < ema_50
            cond_bear_macd  = macd_line < macd_signal and prev_macd_line >= prev_macd_signal
            cond_bear_rsi   = 35 < rsi < 60

            # MTF Gate: 1h bearish only fires if 4h macro is bearish
            bear_passed_all = macro_bearish and cond_bear_trend and cond_bear_macd and cond_bear_rsi

            logger.info(
                f"[1h TA] {ticker} BEAR | 4hMacro:{macro_bearish} Trend:{cond_bear_trend} MACD:{cond_bear_macd} "
                f"RSI:{cond_bear_rsi}({rsi:.1f}) → SHORT={bear_passed_all}"
            )

            if bear_passed_all and not passed_all:
                # ── ATR-Based Dynamic Stop Loss (SHORT) ────────────────────
                stop_loss_distance = atr * 1.5 if atr > 0 else current_price * 0.03
                stop_loss_price = current_price + stop_loss_distance

                logger.info(
                    f"[MTF TA Scanner] BEARISH + 4h macro-bear filters passed for {ticker}! "
                    f"close={candle_close:.2f} EMA20={ema_20:.2f} EMA50={ema_50:.2f} RSI={rsi:.1f} "
                    f"ATR={atr:.2f} SL=${stop_loss_price:.2f}"
                )

                free_usdt = await _exchange.get_free_balance('USDT')
                reserve_usdt   = float(os.getenv("RESERVE_USDT", "0.0"))
                effective_balance = max(0.0, free_usdt - reserve_usdt)

                usdt_to_spend, size_reason = calculate_position_size(
                    free_usdt=effective_balance, 
                    expected_return=0.02, # Neutral default for TA scanner
                    atr=atr, 
                    current_price=current_price
                )

                if usdt_to_spend < 10:
                    logger.warning(f"[MTF TA Scanner] Insufficient capital for SHORT {ticker}.")
                    continue

                amount_to_sell = usdt_to_spend / current_price

                # ── Execution gate: SHORT (Paper vs Real) ────────────────
                if PAPER_TRADE:
                    try:
                        atr_pt = atr if atr > 0 else current_price * 0.01
                        sl_pt = current_price + atr_pt * 1.5
                        tp_pt = current_price - atr_pt * 3.0
                        async with AsyncSessionLocal() as session:
                            pt = PaperTrade(
                                ticker=ticker,
                                action="SHORT",
                                entry_price=current_price,
                                size_usdt=usdt_to_spend,
                                stop_loss=sl_pt,
                                take_profit=tp_pt,
                                status="OPEN",
                                strategy_used="TA_SCANNER_SHORT",
                            )
                            session.add(pt)
                            await session.commit()
                        update_bot_state(action=f"[PAPER] TA SHORT {ticker} @ {current_price:.2f}")
                        logger.info(
                            f"[PAPER TRADE TA] {ticker} SHORT "
                            f"@ {current_price} | SL={sl_pt:.2f} TP={tp_pt:.2f}"
                        )
                        ai_reasoning = f"Bearish MTF Confluence: 1h + 4h (RSI {rsi:.1f}, EMA_20 < EMA_50, 4h Macro Bearish)"
                        await send_entry_alert(
                            ticker=f"[PAPER TRADE] {ticker}",
                            action="SELL",
                            price=current_price,
                            size=usdt_to_spend,
                            stop_loss=sl_pt,
                            confidence=85,
                            ai_reasoning=ai_reasoning,
                            is_ml_hype=False
                        )
                    except Exception as e:
                        logger.error(f"[PAPER TRADE TA] Failed to log short paper trade: {e}")
                else:
                    order = await _exchange.place_order(ticker=ticker, action="SELL", amount=amount_to_sell)

                    if order["status"] == "success":
                        update_bot_state(action=f"[MTF TA] SHORT Opened {amount_to_sell:.4f} {ticker}")
                        async with AsyncSessionLocal() as session:
                            t = Trade(
                                ticker=ticker,
                                action="BUY",           # DB entry marker
                                amount=Decimal(str(order["amount"])),
                                price=Decimal(str(order["price"])),
                                highest_price=Decimal(str(order["price"])),
                                lowest_price=float(order["price"]),
                                stop_loss_price=stop_loss_price,
                                position_size_usdt=usdt_to_spend,
                                status="success",
                                is_closed=False,
                                side="SHORT",
                                reason="mtf_ta_scanner_short",
                            )
                            session.add(t)
                            await session.commit()

                        ai_reasoning = f"Bearish MTF Confluence: 1h + 4h (RSI {rsi:.1f}, EMA_20 < EMA_50, 4h Macro Bearish)"
                        await send_entry_alert(
                            ticker=ticker,
                            action="SELL",
                            price=order["price"],
                            size=usdt_to_spend,
                            stop_loss=stop_loss_price,
                            confidence=85,
                            ai_reasoning=ai_reasoning,
                            is_ml_hype=False
                        )

    except Exception as e:
        logger.error(f"[MTF Scanner Error] {e}", exc_info=True)

async def _automation_loop() -> None:
    """
    24/7 background task:
    Runs News Snipping and TA Scanner in parallel.
    """
    logger.info("Starting GrokSniper AI Automation Loop...")
    
    highest_equity = 0.0
    reported_milestones = set()
    MAJOR_MILESTONES = [500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]

    while True:
        try:
            if config.TRADING_PAUSED:
                update_bot_state(status="⏸️ Paused (Remote Kill Switch)")
                await asyncio.sleep(15)
                continue

            # 1. Start TA Scanner in background
            ta_task = asyncio.create_task(scan_charts_for_opportunities())

            # 2. Poll RSS
            update_bot_state(status="Fetching latest news from RSS...")
            news = await fetch_latest_news()
            if news:
                logger.info(f"Automation: New news found - {news['url']}")
                
                # 2. AI Analyze
                update_bot_state(status="AI Analyzing news...")
                analysis = await analyze_news(news["text"])
                logger.info(f"AI: {analysis.ticker} Score={analysis.sentiment_score} Conf={analysis.confidence}%")

                # ── Pre-filter gate ──────────────────────────────────────────────
                if analysis.ticker not in ("NONE", "UNKNOWN", ""):
                    passed = await passes_pre_filter(analysis.ticker)
                    if not passed:
                        logger.info(
                            f"[AutoLoop] {analysis.ticker} blocked by pre-filter. Skipping CrewAI."
                        )
                        continue

                # Fetch live pre-prediction micro-candles (Phase 32 — no data leakage)
                live_micro = await _fetch_live_micro_candles(analysis.ticker)
                if live_micro:
                    logger.info(f"Live micro-features for {analysis.ticker}: {live_micro}")

                # ML Calibration: adjust raw Groq score using historical market reactions
                raw_score = analysis.sentiment_score
                calibrated_score = calibrate_score(
                    raw_text=news["text"],
                    original_score=raw_score,
                    micro_features=live_micro,
                )
                logger.info(f"ML Calibration: Groq Score {raw_score:.3f} -> ML Adjusted Score {calibrated_score:.3f}")

                # ML Hype Trade Trigger (Phase 29)
                ML_BUY_THRESHOLD = 0.01
                expected_return = predict_return(news["text"], micro_features=live_micro)
                if expected_return is None:
                    expected_return = 0.0
                logger.info(f"ML Prediction for {analysis.ticker}: {expected_return * 100:.2f}%")
                is_hype_trade = (expected_return >= ML_BUY_THRESHOLD) and (analysis.ticker in WATCHLIST)

                # ML SHORT Hype Trigger (Phase 30): strong negative prediction → open SHORT
                ML_SHORT_THRESHOLD = -0.01
                is_short_hype_trade = (expected_return <= ML_SHORT_THRESHOLD) and (analysis.ticker in WATCHLIST)

                update_bot_state(status=f"Analyzing {analysis.ticker} (Score: {calibrated_score:.2f}, Conf: {analysis.confidence}%)")
                
                # Log news to DB (for UI history)
                async with AsyncSessionLocal() as session:
                    log = NewsLog(
                        source=news["source"],
                        raw_text=news["text"],
                        ticker=analysis.ticker,
                        sentiment_score=Decimal(str(analysis.sentiment_score)),
                        confidence=analysis.confidence
                    )
                    session.add(log)
                    await session.commit()

                # 2.5 Telegram News Alert (New Feature)
                sentiment_pct = abs(analysis.sentiment_score) * 100
                sentiment_type = "Бычье (Рост)" if analysis.sentiment_score >= 0 else "Медвежье (Падение)"
                emoji = "🚀" if analysis.sentiment_score >= 0.4 else "📉" if analysis.sentiment_score <= -0.4 else "ℹ️"
                
                news_msg = (
                    f"{emoji} <b>АНАЛИЗ НОВОСТЕЙ: #{analysis.ticker}</b>\n\n"
                    f"<b>Настроение:</b> {sentiment_pct:.0f}% {sentiment_type} (Уверенность: {analysis.confidence}%)\n"
                    f"<b>Мнение ИИ:</b> <i>{analysis.reason}</i>\n\n"
                    f"<a href=\"{news['url']}\">Оригинал статьи</a>\n\n"
                    f"#{analysis.ticker} #NEWS #SENTIMENT"
                )
                await send_telegram_message(news_msg)

                # 3. Risk Gate
                top_20 = await _exchange.get_top_tickers(20)
                is_top_coin = analysis.ticker in top_20
                
                # Check valid ticker
                is_valid_ticker = analysis.ticker not in ["NONE", "UNKNOWN"]
                
                # TA Check for BUY
                ta_approved = False
                rsi = 50.0
                ema_50 = 0.0
                current_volume = 0.0
                volume_sma_20 = 0.0
                current_price_ta = 0.0
                gate_btc = False
                
                if is_valid_ticker:
                    ta_data = await _exchange.get_technical_indicators(analysis.ticker)
                    rsi = ta_data.get("rsi", 50.0)
                    ema_50 = ta_data.get("ema_50", 0.0)
                    current_volume = ta_data.get("current_volume", 0.0)
                    volume_sma_20 = ta_data.get("volume_sma_20", 0.0)
                    current_price_ta = await _exchange.get_price(analysis.ticker)
                    
                    ta_approved = rsi < 70 and current_price_ta > ema_50
                    logger.info(f"TA Check for {analysis.ticker}: RSI={rsi:.2f}, EMA_50={ema_50:.2f}, Vol={current_volume:.2f}, VolSMA20={volume_sma_20:.2f}. TA Approved: {ta_approved}")

                # -----------------------------------------------------------------------
                # Confluence Gate (3 conditions must ALL pass)
                # -----------------------------------------------------------------------
                # Gate 1: ML-Calibrated Sentiment >= 0.5 (uses ML-adjusted score, not raw Groq)
                gate_sentiment = calibrated_score >= 0.5 and analysis.confidence >= 80
                # Gate 2: Volume Anomaly — current volume must be > 1.5x 20-period SMA
                gate_volume = volume_sma_20 > 0 and current_volume > (volume_sma_20 * 1.5)
                # Gate 3: Market Regime — BTC must be healthy for altcoin trades
                if analysis.ticker == "BTC":
                    gate_btc = True
                else:
                    gate_btc = await _exchange.is_btc_healthy()

                # Log individual rejection reasons
                rejection_reason = None
                if not is_valid_ticker:
                    rejection_reason = "Недействительный тикер"
                elif not is_top_coin:
                    rejection_reason = "Не входит в Топ-20 монет"
                elif not gate_sentiment:
                    rejection_reason = f"Слабое настроение (score={calibrated_score:.2f}, нужно ≥0.5)"
                elif not gate_volume:
                    rejection_reason = f"Нет всплеска объёма ({current_volume/volume_sma_20:.1f}x SMA, нужно >1.5x)" if volume_sma_20 > 0 else "Нет данных по объёму"
                elif not gate_btc:
                    rejection_reason = "BTC в медвежьем тренде (фильтр рыночного режима)"
                elif not ta_approved:
                    rejection_reason = f"ТА не одобрен (RSI={rsi:.1f}, цена {'>' if current_price_ta > ema_50 else '<'} EMA50)"

                # Hype trade bypass
                if is_hype_trade and is_valid_ticker and current_price_ta > 0:
                    logger.info(f"🚀 HYPE TRADE TRIGGERED for {analysis.ticker}! Expected Return: {expected_return * 100:.2f}%. Bypassing TA filters.")
                    rejection_reason = None

                if rejection_reason:
                    logger.info(f"Trade rejected for {analysis.ticker}: {rejection_reason}")
                    update_bot_state(action=f"Rejected {analysis.ticker}: {rejection_reason}")

                    # Telegram: Rejected Trade Alert
                    reject_msg = (
                        f"🚫 <b>СДЕЛКА ОТКЛОНЕНА: #{analysis.ticker}</b>\n\n"
                        f"<b>Причина:</b> {rejection_reason}\n"
                        f"<b>Настроение:</b> {calibrated_score:.2f} (исходное: {raw_score:.2f})\n"
                        f"<b>Уверенность:</b> {analysis.confidence}%\n"
                        f"<b>RSI:</b> {rsi:.1f} | <b>Объём:</b> {current_volume/volume_sma_20:.1f}x SMA\n" if volume_sma_20 > 0 else ""
                        f"\n<i>Источник: {news['source']}</i>\n\n"
                        f"#{analysis.ticker} #REJECTED"
                    )
                    await send_telegram_message(reject_msg)
                elif is_hype_trade or (is_top_coin and gate_sentiment and gate_volume and gate_btc and ta_approved):
                    trade_reason = "ml_hype_trade" if is_hype_trade else "ta_confluence"
                    logger.info(f"GATE: Filters passed (or bypassed for ML Hype) for {analysis.ticker}! Evaluating position size.")

                    # Fetch balance for position sizing
                    free_usdt = await _exchange.get_free_balance('USDT')
                    reserve_usdt = float(os.getenv("RESERVE_USDT", "0.0"))
                    effective_balance = max(0.0, free_usdt - reserve_usdt)

                    ta_data = ta_data if is_valid_ticker and 'ta_data' in locals() else await _exchange.get_technical_indicators(analysis.ticker)
                    atr = ta_data.get("atr", 0.0)

                    usdt_to_spend, size_reason = calculate_position_size(
                        free_usdt=effective_balance, 
                        expected_return=expected_return,
                        atr=atr, 
                        current_price=current_price_ta
                    )

                    if usdt_to_spend < 10:
                        logger.warning(f"GATE: Insufficient capital for {analysis.ticker}. Available: {free_usdt:.2f}, Reserve: {reserve_usdt:.2f}, To Spend: {usdt_to_spend:.2f}.")
                    else:
                        amount_to_buy = usdt_to_spend / current_price_ta
                        logger.info(f"GATE: Attempting to BUY {amount_to_buy:.6f} {analysis.ticker} for ~${usdt_to_spend:.2f} USDT")

                        # ── Agent Decision Log (always, regardless of paper/real) ──
                        try:
                            async with AsyncSessionLocal() as session:
                                decision_log = AgentDecisionLog(
                                    ticker=analysis.ticker,
                                    is_approved=True,
                                    confidence=analysis.confidence / 100.0,
                                    cio_reasoning=analysis.reason or "",
                                    market_regime="BULLISH" if gate_btc else "BEARISH",
                                )
                                session.add(decision_log)
                                await session.commit()
                        except Exception as e:
                            logger.warning(f"[AgentDecisionLog] Failed to save: {e}")

                        # ── Execution gate (Paper vs Real) ───────────────────────
                        if PAPER_TRADE:
                            try:
                                current_price = await _exchange.get_price(analysis.ticker)
                                atr_val = ta_data.get("atr", current_price * 0.01) or current_price * 0.01

                                action_str = "LONG"  # news sniper is always a LONG
                                stop_loss_pt = current_price - atr_val * 1.5
                                take_profit_pt = current_price + atr_val * 3.0

                                async with AsyncSessionLocal() as session:
                                    pt = PaperTrade(
                                        ticker=analysis.ticker,
                                        action=action_str,
                                        entry_price=current_price,
                                        size_usdt=usdt_to_spend,
                                        stop_loss=stop_loss_pt,
                                        take_profit=take_profit_pt,
                                        status="OPEN",
                                        strategy_used=trade_reason,
                                    )
                                    session.add(pt)
                                    await session.commit()

                                update_bot_state(action=f"[PAPER] News Sniper: LONG {analysis.ticker} @ {current_price:.2f}")
                                logger.info(
                                    f"[PAPER TRADE] {analysis.ticker} LONG "
                                    f"@ {current_price} | SL={stop_loss_pt:.2f} TP={take_profit_pt:.2f}"
                                )
                                ai_reasoning = analysis.reason if not is_hype_trade else f"Expected Return (1h): {expected_return*100:.2f}%"
                                await send_entry_alert(
                                    ticker=f"[PAPER TRADE] {analysis.ticker}",
                                    action="BUY",
                                    price=current_price,
                                    size=usdt_to_spend,
                                    stop_loss=stop_loss_pt,
                                    confidence=analysis.confidence if not is_hype_trade else 90,
                                    ai_reasoning=ai_reasoning,
                                    is_ml_hype=is_hype_trade
                                )
                            except Exception as e:
                                logger.error(f"[PAPER TRADE] Failed to log paper trade: {e}")
                        else:
                            # 4. Place Real Order
                            order = await _exchange.place_order(
                                ticker=analysis.ticker,
                                action="BUY",
                                amount=amount_to_buy
                            )

                            # Save Trade to DB
                            if order["status"] == "success":
                                update_bot_state(action=f"News Sniper: Bought {amount_to_buy:.4f} {analysis.ticker}")
                                async with AsyncSessionLocal() as session:
                                    t = Trade(
                                        ticker=analysis.ticker,
                                        action="BUY",
                                        amount=Decimal(str(order["amount"])),
                                        price=Decimal(str(order["price"])),
                                        highest_price=Decimal(str(order["price"])),
                                        position_size_usdt=usdt_to_spend,
                                        status="success",
                                        is_closed=False,
                                        reason=trade_reason
                                    )
                                    session.add(t)
                                    await session.commit()

                                ai_reasoning = analysis.reason if not is_hype_trade else f"Expected Return (1h): {expected_return*100:.2f}%"
                                await send_entry_alert(
                                    ticker=analysis.ticker,
                                    action="BUY",
                                    price=order["price"],
                                    size=usdt_to_spend,
                                    stop_loss=current_price_ta - (atr * 1.5 if atr > 0 else current_price_ta * 0.03),
                                    confidence=analysis.confidence if not is_hype_trade else 90,
                                    ai_reasoning=ai_reasoning,
                                    is_ml_hype=is_hype_trade
                                )
                else:
                    logger.info(f"GATE: {analysis.ticker} did not meet all confluence filters. No trade placed.")

                # ── ML SHORT Hype Trade (Phase 30) ────────────────────────
                # If negative ML prediction and no LONG trade was placed, open SHORT
                if is_short_hype_trade and is_valid_ticker and current_price_ta > 0 and not is_hype_trade:
                    logger.info(f"📉 ML SHORT HYPE TRIGGERED for {analysis.ticker}! Expected Return: {expected_return * 100:.2f}%. Opening SHORT.")

                    free_usdt = await _exchange.get_free_balance('USDT')
                    reserve_usdt = float(os.getenv("RESERVE_USDT", "0.0"))
                    effective_balance = max(0.0, free_usdt - reserve_usdt)

                    ta_data = ta_data if is_valid_ticker and 'ta_data' in locals() else await _exchange.get_technical_indicators(analysis.ticker)
                    atr = ta_data.get("atr", 0.0)

                    usdt_to_spend, size_reason = calculate_position_size(
                        free_usdt=effective_balance, 
                        expected_return=expected_return,
                        atr=atr, 
                        current_price=current_price_ta
                    )

                    if usdt_to_spend >= 10:
                        amount_to_sell = usdt_to_spend / current_price_ta

                        # NOTE: SELL to Open the short position.
                        # Account must be in Margin/Futures mode on Binance.
                        order = await _exchange.place_order(
                            ticker=analysis.ticker,
                            action="SELL",
                            amount=amount_to_sell
                        )

                        if order["status"] == "success":
                            update_bot_state(action=f"ML SHORT: Sold {amount_to_sell:.4f} {analysis.ticker}")
                            async with AsyncSessionLocal() as session:
                                t = Trade(
                                    ticker=analysis.ticker,
                                    action="BUY",           # DB entry marker
                                    amount=Decimal(str(order["amount"])),
                                    price=Decimal(str(order["price"])),
                                    highest_price=Decimal(str(order["price"])),
                                    lowest_price=float(order["price"]),
                                    position_size_usdt=usdt_to_spend,
                                    status="success",
                                    is_closed=False,
                                    side="SHORT",
                                    reason="ml_hype_short",
                                )
                                session.add(t)
                                await session.commit()

                            ai_reasoning = f"Expected Return (1h): {expected_return*100:.2f}% | ML Hype Short Triggered"
                            await send_entry_alert(
                                ticker=analysis.ticker,
                                action="SELL",
                                price=order["price"],
                                size=usdt_to_spend,
                                stop_loss=current_price_ta + (atr * 1.5 if atr > 0 else current_price_ta * 0.03),
                                confidence=90,
                                ai_reasoning=ai_reasoning,
                                is_ml_hype=True
                            )

            # Ensure TA scanner finishes this cycle
            await ta_task

            # NOTE: Position management (stop loss / take profit / trailing stop)
            # is now handled in real-time by the WebSocket supervisor task
            # (monitor_open_positions_ws) started in lifespan — no REST polling needed here.

            # -----------------------------------------------------------------------
            # 7. Milestone & Equity Check
            # -----------------------------------------------------------------------
            try:
                balance_data = await _exchange.get_balance()
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
                            f"Рекомендуем обновить <code>RESERVE_USDT</code> в файле <code>.env</code>, чтобы зафиксировать прибыль.\n\n"
                            f"#MILESTONE #ПРИБЫЛЬ"
                        )
                        await send_telegram_message(msg)
            except Exception as e:
                logger.error(f"Milestone Check Error: {e}")

        except Exception as e:
            logger.error(f"Automation Loop Error: {e}")
        
        update_bot_state(status="Idle (Waiting for next cycle...)")
        await asyncio.sleep(60)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Database Initialization ──────────────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Base.metadata.create_all executed successfully.")
    except Exception as e:
        logger.error(f"DB Initialization error: {e}")

    # Defensive Migration for Phase 17
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN highest_price NUMERIC(24, 8);"))
            logger.info("DB Migration: Added highest_price column to trades table.")
    except Exception:
        pass
        
    # Defensive Migration for Phase 29
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN reason VARCHAR(50);"))
            logger.info("DB Migration: Added reason column to trades table.")
    except Exception:
        pass

    # Defensive Migration for Phase 30 (Short Selling)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN side VARCHAR(10) DEFAULT 'LONG';"))
            logger.info("DB Migration: Added side column to trades table.")
    except Exception:
        pass
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN lowest_price FLOAT;"))
            logger.info("DB Migration: Added lowest_price column to trades table.")
    except Exception:
        pass

    # Defensive Migration for Phase 32 (ATR Dynamic Stops + Micro-Features)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN stop_loss_price FLOAT;"))
            logger.info("DB Migration: Added stop_loss_price column to trades table.")
    except Exception:
        pass
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE news_logs ADD COLUMN micro_features TEXT;"))
            logger.info("DB Migration: Added micro_features column to news_logs table.")
    except Exception:
        pass
        
    # Defensive Migration for Phase 33 (Smart Position Sizing)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN position_size_usdt FLOAT;"))
            logger.info("DB Migration: Added position_size_usdt column to trades table.")
    except Exception:
        pass

    # Defensive Migration for Phase 39 (Paper Trading & Logic Logging)
    try:
        # We already ran Base.metadata.create_all at the top, but running it again
        # ensures any newly imported models not previously created are added.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("DB migrations: paper_trades and agent_decision_logs tables ready.")
    except Exception as e:
        logger.warning(f"DB migration warning: {e}")

    logger.info("DB Initialized.")

    # ── Startup Telegram Alert ──────────────────────────────────────────
    try:
        balance_data = await _exchange.get_balance()
        total_usdt = balance_data.get("total_usdt", 0.0)
        startup_msg = (
            f"🟢 <b>GROKSNIPER AI — ЗАПУЩЕН</b>\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"💰 <b>Баланс:</b> ${total_usdt:,.2f}\n"
            f"📡 <b>Watchlist:</b> {', '.join(WATCHLIST)}\n"
            f"🔧 <b>Стратегия:</b> Institutional Flow | TA/News\n\n"
            f"Бот полностью активен. Удачной торговли! 🚀\n\n"
            f"#STARTUP #SYSTEM_ONLINE"
        )
        
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📊 Статус", "callback_data": "btn_status"},
                    {"text": "⏸️ Пауза", "callback_data": "btn_pause"}
                ]
            ]
        }
        await send_telegram_message(startup_msg, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Startup alert failed: {e}")

    # ── Start Telegram Command Center ───────────────────────────────────
    tg_app = get_telegram_app()
    if tg_app:
        await start_telegram_listener(tg_app)

    # Task 1: 60-second RSS + TA scanner loop
    auto_task = asyncio.create_task(_automation_loop())
    logger.info("Automation task started.")

    # Task 2: Real-time WebSocket position monitor (Phase 24)
    ws_task = asyncio.create_task(monitor_open_positions_ws())
    logger.info("WebSocket position monitor started.")

    # Task 3: Periodic portfolio summary (every 4h)
    summary_task = asyncio.create_task(_portfolio_summary_loop())
    logger.info("Periodic summary task started.")

    logger.info("Live Engine loaded with Golden Strategy: 3% SL, 10% TP, 4% Trail Activation.")

    yield

    # Graceful shutdown
    # ── Shutdown Telegram Alert ─────────────────────────────────────────
    try:
        shutdown_msg = (
            f"🔴 <b>GROKSNIPER AI — ОСТАНОВЛЕН</b>\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Бот остановлен. До следующего запуска!"
        )
        await send_telegram_message(shutdown_msg)
    except Exception:
        pass

    auto_task.cancel()
    ws_task.cancel()
    summary_task.cancel()
    cancel_all_watchers()   # cancel all per-trade watcher sub-tasks
    
    if tg_app:
        await stop_telegram_listener(tg_app)
        
    for task in [auto_task, ws_task, summary_task]:
        try:
            await task
        except asyncio.CancelledError:
            pass
    await engine.dispose()

# ---------------------------------------------------------------------------
# API Server setup
# ---------------------------------------------------------------------------
app = FastAPI(title="GrokSniper AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes (Keeping existing for UI)
class NewsResponse(BaseModel):
    id: str
    source: str
    raw_text: str
    ticker: str | None
    sentiment_score: float | None
    confidence: int | None
    created_at: str
    model_config = {"from_attributes": True}


class TradeResponse(BaseModel):
    id: UUID
    ticker: str
    action: str
    amount: float
    price: float
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    position_size_usdt: Optional[float] = None
    side: Optional[str] = None
    reason: Optional[str] = None
    status: str
    is_closed: bool
    parent_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True

class HoldingItem(BaseModel):
    coin: str
    amount: float
    value_usdt: float

class StatsResponse(BaseModel):
    total_balance: float
    pnl_24h: float
    total_trades: int
    signals_processed: int
    holdings: list[HoldingItem] = []

class ManualTradeRequest(BaseModel):
    ticker: str
    amount_usdt: float

def _decimal_to_float(val) -> float | None:
    return float(val) if isinstance(val, Decimal) else val

@app.get("/api/bot-status", response_model=dict)
async def get_bot_status():
    """Returns the real-time cognitive state of the bot."""
    return bot_state

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Fetches real-time stats including Binance balance and DB counts."""
    balance_data = await _exchange.get_balance()
    initial_equity = float(os.getenv("INITIAL_EQUITY", "10000.0"))
    total_usdt = balance_data.get("total_usdt", initial_equity)
    pnl = total_usdt - initial_equity
    holdings = balance_data.get("holdings", [])

    async with AsyncSessionLocal() as session:
        trades_count = (await session.execute(text("SELECT count(*) FROM trades"))).scalar() or 0
        news_count = (await session.execute(text("SELECT count(*) FROM news_logs"))).scalar() or 0

    return StatsResponse(
        total_balance=total_usdt,
        pnl_24h=pnl,
        total_trades=trades_count,
        signals_processed=news_count,
        holdings=holdings
    )

@app.get("/api/news", response_model=list[NewsResponse])
async def get_news():
    async with AsyncSessionLocal() as session:
        # Limit to 50 and truncate raw_text to 300 chars to prevent lag
        res = await session.execute(select(NewsLog).order_by(NewsLog.created_at.desc()).limit(50))
        return [NewsResponse(
            id=str(r.id), source=r.source, 
            raw_text=(r.raw_text[:300] + "...") if len(r.raw_text) > 300 else r.raw_text,
            ticker=r.ticker, sentiment_score=float(r.sentiment_score) if r.sentiment_score else None,
            confidence=r.confidence, created_at=r.created_at.isoformat()
        ) for r in res.scalars().all()]

@app.get("/api/trades", response_model=list[TradeResponse])
async def get_trades():
    async with AsyncSessionLocal() as session:
        # Limit to 50 most recent records
        result = await session.execute(
            select(Trade).order_by(Trade.created_at.desc()).limit(50)
        )
        rows = result.scalars().all()

    return [
        TradeResponse(
            id=str(row.id),
            ticker=row.ticker,
            action=row.action,
            amount=_decimal_to_float(row.amount),
            price=_decimal_to_float(row.price),
            highest_price=_decimal_to_float(row.highest_price),
            lowest_price=_decimal_to_float(row.lowest_price),
            stop_loss_price=_decimal_to_float(row.stop_loss_price) if hasattr(row, 'stop_loss_price') else None,
            position_size_usdt=_decimal_to_float(row.position_size_usdt) if hasattr(row, 'position_size_usdt') else None,
            side=row.side,
            reason=row.reason,
            status="success" if row.status.lower() in ["filled", "completed", "success"] else row.status,
            is_closed=row.is_closed,
            parent_id=row.parent_id,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "FULL_AUTOMATION"}

    

@app.post("/api/trigger")
async def trigger_manual_check():
    try:
        new_story = await fetch_latest_news()
        count = 1 if new_story else 0
        return {"status": "success", "message": "Scanned", "count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/buy")
async def manual_buy(req: ManualTradeRequest):
    """Executes a manual MARKET BUY to open a LONG position."""
    try:
        current_price = await _exchange.get_price(req.ticker)
        if current_price <= 0:
            return {"status": "error", "message": "Failed to fetch price"}

        amount_to_buy = req.amount_usdt / current_price
        order = await _exchange.place_order(ticker=req.ticker, action="BUY", amount=amount_to_buy)

        if order["status"] == "success":
            # Dynamic SL is not accurately computable without full TA pass, fallback to 3% hard stop
            stop_loss_price = current_price * 0.97
            
            async with AsyncSessionLocal() as session:
                t = Trade(
                    ticker=req.ticker,
                    action="BUY",
                    amount=Decimal(str(order["amount"])),
                    price=Decimal(str(order["price"])),
                    highest_price=Decimal(str(order["price"])),
                    stop_loss_price=stop_loss_price,
                    position_size_usdt=req.amount_usdt,
                    status="success",
                    is_closed=False,
                    reason="manual_trade_long"
                )
                session.add(t)
                await session.commit()

            await send_entry_alert(
                ticker=req.ticker,
                action="BUY",
                price=float(order["price"]),
                size=req.amount_usdt,
                stop_loss=stop_loss_price,
                confidence=100,
                ai_reasoning="Manual execution via Dashboard.",
                event_type="СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ (MANUAL)"
            )
            return {"status": "success", "order": order}

        return {"status": "error", "message": "Order failed", "details": order}
    except Exception as e:
        logger.error(f"Manual BUY failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@app.post("/api/sell")
async def manual_sell(req: ManualTradeRequest):
    """Executes a manual MARKET SELL to open a SHORT position."""
    try:
        current_price = await _exchange.get_price(req.ticker)
        if current_price <= 0:
            return {"status": "error", "message": "Failed to fetch price"}

        amount_to_sell = req.amount_usdt / current_price
        order = await _exchange.place_order(ticker=req.ticker, action="SELL", amount=amount_to_sell)

        if order["status"] == "success":
            # Dynamic SL fallback to 3% hard stop
            stop_loss_price = current_price * 1.03
            
            async with AsyncSessionLocal() as session:
                t = Trade(
                    ticker=req.ticker,
                    action="BUY", # Marker for open trade in DB
                    amount=Decimal(str(order["amount"])),
                    price=Decimal(str(order["price"])),
                    highest_price=Decimal(str(order["price"])),
                    lowest_price=float(order["price"]),
                    stop_loss_price=stop_loss_price,
                    position_size_usdt=req.amount_usdt,
                    status="success",
                    is_closed=False,
                    side="SHORT",
                    reason="manual_trade_short"
                )
                session.add(t)
                await session.commit()

            await send_entry_alert(
                ticker=req.ticker,
                action="SELL",
                price=float(order["price"]),
                size=req.amount_usdt,
                stop_loss=stop_loss_price,
                confidence=100,
                ai_reasoning="Manual execution via Dashboard.",
                event_type="СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ (MANUAL)"
            )
            return {"status": "success", "order": order}

        return {"status": "error", "message": "Order failed", "details": order}
    except Exception as e:
        logger.error(f"Manual SELL failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

# ---------------------------------------------------------------------------
# WebSocket — Dashboard Live Feed
# ---------------------------------------------------------------------------
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    Long-lived WebSocket connection for the dashboard frontend.
    Immediately pushes the current bot_state as a greeting,
    then stays open to receive server-side push events.
    """
    await dashboard_ws_manager.connect(websocket)
    try:
        # Send current state immediately on connect so UI is not blank
        await websocket.send_text(json.dumps({"type": "bot_state", **bot_state}))
        # Keep alive — heartbeat every 20s to detect dead connections
        while True:
            await asyncio.sleep(20)
            await websocket.send_text(json.dumps({"type": "heartbeat", "ts": datetime.utcnow().isoformat()}))
    except WebSocketDisconnect:
        dashboard_ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS Dashboard] Unexpected error: {e}")
        dashboard_ws_manager.disconnect(websocket)

# ---------------------------------------------------------------------------
# REST — Trade AI Reasoning lookup (for expandable rows in trades page)
# ---------------------------------------------------------------------------
@app.get("/api/trades/{trade_id}/reasoning")
async def get_trade_reasoning(trade_id: str):
    """
    Looks up the AgentDecisionLog closest in time to a given trade.
    Returns CIO reasoning and market regime for the expandable trade row.
    """
    try:
        async with AsyncSessionLocal() as session:
            trade_result = await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )
            trade = trade_result.scalar_one_or_none()
            if not trade:
                return {"reasoning": None, "regime": None, "confidence": None}

            # Find closest agent decision log for this ticker by timestamp proximity
            log_result = await session.execute(
                select(AgentDecisionLog)
                .where(AgentDecisionLog.ticker == trade.ticker)
                .order_by(
                    text(f"ABS(EXTRACT(EPOCH FROM (created_at - TIMESTAMP '{trade.created_at.isoformat()}')))")
                )
                .limit(1)
            )
            log = log_result.scalar_one_or_none()
            if not log:
                return {"reasoning": "No AI reasoning recorded for this trade.", "regime": "N/A", "confidence": None}

            return {
                "reasoning": log.cio_reasoning,
                "regime": log.market_regime,
                "confidence": round(log.confidence * 100) if log.confidence else None,
                "is_approved": log.is_approved,
            }
    except Exception as e:
        logger.error(f"[TradeReasoning] Error: {e}")
        return {"reasoning": "Error fetching reasoning.", "regime": None, "confidence": None}

# ---------------------------------------------------------------------------
# REST — Advanced Analytics (Phase 42)
# ---------------------------------------------------------------------------
@app.get("/api/analytics")
async def get_analytics():
    """
    Returns performance metrics and equity curve based on closed PaperTrades.
    """
    try:
        async with AsyncSessionLocal() as session:
            # Query all closed paper trades ascending by time
            result = await session.execute(
                select(PaperTrade)
                .where(PaperTrade.status == "CLOSED")
                .order_by(PaperTrade.created_at.asc())
            )
            trades = result.scalars().all()

            total_trades = len(trades)
            if total_trades == 0:
                return {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "equity_curve": []
                }

            winning_trades = sum(1 for t in trades if t.pnl_usdt is not None and t.pnl_usdt > 0)
            win_rate = winning_trades / total_trades
            total_pnl = sum(t.pnl_usdt for t in trades if t.pnl_usdt is not None)

            equity_curve = []
            cumulative = 0.0
            for t in trades:
                pnl = t.pnl_usdt or 0.0
                cumulative += pnl
                equity_curve.append({
                    "date": t.created_at.isoformat(),
                    "cumulative_pnl": round(cumulative, 2),
                    "trade_pnl": round(pnl, 2),
                    "ticker": t.ticker
                })

            return {
                "total_trades": total_trades,
                "win_rate": round(win_rate * 100, 2),
                "total_pnl": round(total_pnl, 2),
                "equity_curve": equity_curve
            }
    except Exception as e:
        logger.error(f"[Analytics] Error: {e}")
        return {"error": str(e)}
