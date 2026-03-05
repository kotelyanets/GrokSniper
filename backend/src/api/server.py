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
from backend.src.ml.predictor import calibrate_score, predict_return
import backend.src.config as config
from backend.src.services.execution_engine import execute_sniper_order, build_exec_tag
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message, send_exit_alert
from backend.src.services.telegram_listener import get_telegram_app, start_telegram_listener, stop_telegram_listener
from backend.src.services.ws_manager import monitor_open_positions_ws, cancel_all_watchers
from backend.src.services.rss_scraper import fetch_latest_news


logger = logging.getLogger("groksniper.api")

# Shared instances
_exchange = CryptoExchange()

# ---------------------------------------------------------------------------
# Phase 48 — Regime state cache (updated once per cycle, shared across tickers)
# ---------------------------------------------------------------------------
_current_regime = "PURE_AI"
_regime_params  = {}
_regime_confidence = 100.0

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


# ---------------------------------------------------------------------------
# Phase 44.3 WFV-validated strategy stats (used by Kelly Criterion)
# Updated automatically by future runs of the backtester.
# Win rate and avg win/loss derived from the 3-year stress test Pareto-BALANCED profile.
# ---------------------------------------------------------------------------
_KELLY_WIN_RATE   = 0.52    # historical win rate (52%)
_KELLY_AVG_WIN    = 4.20    # avg winning trade return (%)
_KELLY_AVG_LOSS   = 2.80    # avg losing trade return (%) — positive value
_KELLY_MAX_FRAC   = 0.25    # hard cap: never risk more than 25% of balance
_KELLY_SCALE      = 0.50    # fractional Kelly (half-Kelly) → reduces variance


def _kelly_fraction() -> float:
    """
    Full Kelly formula: f* = W - (1-W)/RR
    where W = win rate, RR = avg_win / avg_loss.
    Returns the HALF-Kelly fraction (×0.5) capped at _KELLY_MAX_FRAC.
    """
    W  = _KELLY_WIN_RATE
    RR = _KELLY_AVG_WIN / max(_KELLY_AVG_LOSS, 0.01)
    kelly_full = W - (1.0 - W) / RR
    kelly_full = max(kelly_full, 0.0)            # Kelly can be negative — floor at 0
    return min(kelly_full * _KELLY_SCALE, _KELLY_MAX_FRAC)


def calculate_position_size(
    free_usdt: float,
    expected_return: float,
    atr: float,
    current_price: float,
) -> tuple[float, str]:
    """
    Phase 47 — Kelly Criterion + ML Confidence + Volatility sizing.

    Steps:
      1. Compute Half-Kelly base fraction from historical win/loss stats.
      2. Scale up/down by ML confidence (expected_return signal).
      3. Apply an ATR volatility penalty to avoid over-sizing in choppy markets.
      4. Hard-cap at _KELLY_MAX_FRAC (25%) to prevent ruin.

    Returns (usdt_to_spend, sizing_reason).
    """
    # ── 1. Kelly base fraction ──────────────────────────────────────────────
    kelly_frac = _kelly_fraction()               # e.g. 0.09 (9% of balance)

    # ── 2. ML Confidence Multiplier ────────────────────────────────────────
    # Scale Kelly fraction: strong signal → up to 1.5× Kelly; weak → 0.5× Kelly
    abs_ret = abs(expected_return)
    if abs_ret >= 0.03:
        ml_mult = 1.50    # Strong conviction: allow up to 1.5× Kelly
    elif abs_ret >= 0.01:
        ml_mult = 1.0 + (abs_ret - 0.01) / 0.02 * 0.50   # 1.0—1.5×
    else:
        ml_mult = 0.50    # Weak signal: half the Kelly fraction

    # ── 3. Volatility Penalty (ATR as % of price) ──────────────────────────
    vol_penalty = 1.0
    if current_price > 0:
        atr_pct = atr / current_price
        if atr_pct > 0.04:
            vol_penalty = 0.50          # Very choppy market — halve size
        elif atr_pct > 0.02:
            vol_penalty = 1.0 - ((atr_pct - 0.02) / 0.02) * 0.50

    # ── 4. Combine & cap ───────────────────────────────────────────────────
    effective_frac = kelly_frac * ml_mult * vol_penalty
    effective_frac = min(effective_frac, _KELLY_MAX_FRAC)
    effective_frac = max(effective_frac, 0.01)   # Always at least 1%

    raw_size   = free_usdt * effective_frac
    final_size = max(raw_size, 10.0)             # Binance minimum $10
    final_size = min(final_size, free_usdt * _KELLY_MAX_FRAC)

    # ── Reasoning string for Telegram ──────────────────────────────────────
    conf_str = "HighConf" if ml_mult > 1.2 else "NormConf" if ml_mult >= 0.8 else "LowConf"
    vol_str  = "HighVol" if vol_penalty < 0.7 else "NormVol"
    reason   = (f"Kelly {kelly_frac*100:.1f}% × {ml_mult:.2f}× ML × {vol_penalty:.2f}× Vol "
                f"= {effective_frac*100:.1f}% ({conf_str}, {vol_str})")

    return final_size, reason


async def _automation_loop() -> None:
    """
    24/7 background task:
    Runs News Snipping and Pure AI Engine.
    """
    logger.info("Starting GrokSniper Pure AI Automation Loop...")
    
    highest_equity = 0.0
    reported_milestones = set()
    MAJOR_MILESTONES = [500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]

    while True:
        try:
            if config.TRADING_PAUSED:
                update_bot_state(status="⏸️ Paused (Remote Kill Switch)")
                await asyncio.sleep(15)
                continue

            # Fetch news once per cycle (to be shared across all tickers)
            update_bot_state(status="Fetching latest market news...")
            news_record = await fetch_latest_news()
            news_text = news_record["text"] if news_record else ""

            # Run the Pure AI Engine (Phase 8 Batch mode)
            update_bot_state(status="🧠 Running Pure AI Engine (Claude Opus)...")
            logger.info("Starting Pure AI Engine batch scan for all tickers.")
            
            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers(latest_news=news_text)
            
            # Log summary
            executed = [r["ticker"] for r in results if r.get("trade_placed")]
            skipped = [r["ticker"] for r in results if not r.get("trade_placed") and r.get("action") != "HOLD"]
            held = [r["ticker"] for r in results if r.get("action") == "HOLD"]
            
            logger.info(f"AI Engine Cycle Complete. Executed: {len(executed)} | Held: {len(held)} | Skipped: {len(skipped)}")
            if executed:
                logger.info(f"Executed trades for: {', '.join(executed)}")

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
            logger.error(f"Automation Loop Error: {e}", exc_info=True)
        
        update_bot_state(status="Idle (Waiting for next cycle...)")
        scan_interval = int(os.getenv("SCAN_INTERVAL", "900"))
        await asyncio.sleep(scan_interval)

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

    # Defensive Migration for ai_reasoning
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE paper_trades ADD COLUMN ai_reasoning TEXT;"))
            logger.info("DB Migration: Added ai_reasoning column to paper_trades table.")
    except Exception:
        pass

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

    logger.info("Live Engine loaded with Hyper-Trend Strategy: ATR SL, No Hard TP, 2% Trail Activation.")

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
    
    # Advanced Dashboard Metrics
    ai_efficiency: float = 0.0
    burn_rate: float = 0.0
    system_health: str = "ONLINE"
    total_invested: float = 0.0
    active_leverage: float = 0.0
    avg_leverage: float = 0.0
    tokens_consumed: int = 0
    ai_analysis_count: int = 0
    api_calls: int = 0

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
    initial_equity = float(os.getenv("INITIAL_EQUITY", "1000.0"))
    total_usdt = balance_data.get("total_usdt")
    if not total_usdt:
        total_usdt = initial_equity
    pnl = total_usdt - initial_equity
    holdings = balance_data.get("holdings", [])

    async with AsyncSessionLocal() as session:
        # 1. Base counts
        trades_count = (await session.execute(text("SELECT count(*) FROM trades"))).scalar() or 0
        news_count = (await session.execute(text("SELECT count(*) FROM news_logs"))).scalar() or 0
        
        # 2. Investment Overview
        result = await session.execute(select(Trade).where(Trade.is_closed == False))
        open_trades = result.scalars().all()
        total_invested = sum([float(t.amount * t.price) for t in open_trades]) if open_trades else 0.0
        active_leverage = len(open_trades)
        avg_leverage = 1.0  # Default spot leverage
        
        # 3. AI Performance & Cost (Mocked until exact DB tracking is added)
        mock_ai_efficiency = 87.5
        mock_tokens = 72728 + (trades_count * 1200) + (news_count * 450)
        mock_burn_rate = 0.59 + ((mock_tokens - 72728) * 0.000008)
        mock_system_health = "ONLINE"
        mock_analyses = trades_count + int(news_count / 5)
        mock_api_calls = 53 + trades_count + news_count

    return StatsResponse(
        total_balance=total_usdt,
        pnl_24h=pnl,
        total_trades=trades_count,
        signals_processed=news_count,
        holdings=holdings,
        ai_efficiency=mock_ai_efficiency,
        burn_rate=mock_burn_rate,
        system_health=mock_system_health,
        total_invested=total_invested,
        active_leverage=float(active_leverage),
        avg_leverage=avg_leverage,
        tokens_consumed=mock_tokens,
        ai_analysis_count=mock_analyses,
        api_calls=mock_api_calls
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


@app.post("/api/reset-paper-test")
async def reset_paper_test():
    """
    ⚠️ DANGER: Wipes ALL trades, paper trades, news logs, and agent logs.
    Use only to start a fresh forward test. The simulated balance resets to
    INITIAL_EQUITY (default $10,000) automatically because DRY_RUN returns
    that value on every get_balance() call.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM trades"))
            await session.execute(text("DELETE FROM paper_trades"))
            await session.execute(text("DELETE FROM news_logs"))
            # agent_decision_logs may not exist in every deploy — ignore if missing
            try:
                await session.execute(text("DELETE FROM agent_decision_logs"))
            except Exception:
                pass
            await session.commit()

        initial_equity = float(os.getenv("INITIAL_EQUITY", "10000.0"))
        logger.warning("🔄 Paper test RESET — all trades and logs wiped. Virtual balance: $%.2f", initial_equity)
        return {
            "status": "success",
            "message": f"Paper test reset. Starting balance: ${initial_equity:,.2f}",
            "initial_equity": initial_equity
        }
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        return {"status": "error", "message": str(e)}

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

@app.post("/api/trades/{trade_id}/close")
async def manual_close(trade_id: str):
    """Manually closes an open (is_closed=False) position."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade).where(Trade.id == trade_id))
            trade = result.scalar_one_or_none()
            
            if not trade:
                return {"status": "error", "message": "Trade not found"}
            if trade.is_closed:
                return {"status": "error", "message": "Trade is already closed"}
            if trade.action != "BUY":
                # Assuming only 'BUY' actions open positions
                return {"status": "error", "message": "Only BUY (open) positions can be closed"}

            ticker = trade.ticker
            side = trade.side or "LONG"
            entry_price = float(trade.price)
            close_action = "BUY" if side == "SHORT" else "SELL"
            
            # Get current price
            current_price = await _exchange.get_price(ticker)
            if current_price <= 0:
                current_price = float(trade.highest_price) if side == "LONG" else float(trade.lowest_price)

            is_paper = os.getenv("PAPER_TRADE", "False").lower() == "true"
            close_amount = float(trade.amount)

            # Execute Order
            if is_paper:
                close_order = {"status": "success", "price": current_price, "amount": close_amount}
            else:
                close_order = await _exchange.place_order(ticker=ticker, action=close_action, amount=0)
            
            if close_order["status"] != "success":
                return {"status": "error", "message": "Failed to place closing order"}

            exec_price = float(close_order["price"])
            
            if side == "SHORT":
                pnl_pct = ((entry_price - exec_price) / entry_price) * 100
                pnl_usd = (entry_price - exec_price) * close_amount
            else:
                pnl_pct = ((exec_price - entry_price) / entry_price) * 100
                pnl_usd = (exec_price - entry_price) * close_amount

            # Update DB
            trade.is_closed = True
            
            s = Trade(
                ticker=ticker,
                action="SELL" if side == "SHORT" else "SELL", # Standardized logging format
                amount=Decimal(str(close_amount)),
                price=Decimal(str(exec_price)),
                status="success",
                is_closed=True,
                parent_id=trade.id,
                side=side,
            )
            session.add(s)
            await session.commit()

        # Send alert
        await send_exit_alert(
            ticker=ticker,
            exit_label="Manual Close via Dashboard",
            entry_price=entry_price,
            exit_price=exec_price,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            side=side,
            reference_price=current_price
        )
        return {"status": "success", "message": "Position closed"}
    except Exception as e:
        logger.error(f"Manual CLOSE failed: {e}", exc_info=True)
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
    except asyncio.CancelledError:
        dashboard_ws_manager.disconnect(websocket)
        # Graceful exit on server shutdown to prevent Uvicorn traceback
        return
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
