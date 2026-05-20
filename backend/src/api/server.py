"""
server.py
---------
GrokSniper AI — FastAPI application bootstrap.

This file is intentionally thin. Business logic lives in:
  backend.src.api.state       — shared bot state & WebSocket manager
  backend.src.api.sizing      — Kelly Criterion position sizing
  backend.src.api.automation  — 24/7 background tasks & portfolio summary
  backend.src.api.routes      — all REST & WebSocket endpoint handlers
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.src.api.automation import _automation_loop, _portfolio_summary_loop, _ml_training_loop, _pnl_heartbeat_loop
from backend.src.api.routes import router
from backend.src.api.state import WATCHLIST
from backend.src.db.database import Base, engine
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message
from backend.src.services.telegram_listener import (
    get_telegram_app,
    start_telegram_listener,
    stop_telegram_listener,
)
from backend.src.services.ws_manager import cancel_all_watchers, monitor_open_positions_ws
from backend.src.services.paper_trade_closer import paper_trade_closer_loop
from backend.src.services.position_reconciler import reconcile_positions_loop

from datetime import datetime

logger    = logging.getLogger("groksniper.api")
_exchange = CryptoExchange()

# ---------------------------------------------------------------------------
# Lifespan — DB setup, background tasks, Telegram alerts
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Database Initialization ──────────────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("DB tables created / verified.")
    except Exception as e:
        logger.error(f"DB Initialization error: {e}")

    # Defensive schema migrations (idempotent — fail silently if column exists)
    _migrations = [
        "ALTER TABLE trades ADD COLUMN highest_price NUMERIC(24, 8)",
        "ALTER TABLE trades ADD COLUMN reason TEXT",
        "ALTER TABLE trades ALTER COLUMN reason TYPE TEXT",
        "ALTER TABLE trades ADD COLUMN side VARCHAR(10) DEFAULT 'LONG'",
        "ALTER TABLE trades ADD COLUMN lowest_price FLOAT",
        "ALTER TABLE trades ADD COLUMN stop_loss_price FLOAT",
        "ALTER TABLE trades ADD COLUMN position_size_usdt FLOAT",
        "ALTER TABLE news_logs ADD COLUMN micro_features TEXT",
        "ALTER TABLE paper_trades ADD COLUMN ai_reasoning TEXT",
        "ALTER TABLE paper_trades ADD COLUMN analysis_report TEXT",
    ]
    for sql in _migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"{sql};"))
        except Exception:
            pass  # Column already exists — expected on every restart after first run

    # Second create_all pass to handle new ORM models added after first deploy
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.warning(f"Second create_all warning: {e}")

    logger.info("DB Initialized.")

    # ── Startup Telegram Alert ──────────────────────────────────────────
    try:
        balance_data = await _exchange.get_balance()
        total_usdt   = balance_data.get("total_usdt", 0.0)
        startup_msg  = (
            f"🟢 <b>GROKSNIPER AI — ЗАПУЩЕН</b>\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"💰 <b>Баланс:</b> ${total_usdt:,.2f}\n"
            f"📡 <b>Watchlist:</b> {', '.join(WATCHLIST)}\n"
            f"🔧 <b>Стратегия:</b> Institutional Flow | TA/News\n\n"
            f"Бот полностью активен. Удачной торговли! 🚀\n\n"
            f"#STARTUP #SYSTEM_ONLINE"
        )
        reply_markup = {"inline_keyboard": [[
            {"text": "📊 Статус", "callback_data": "btn_status"},
            {"text": "⏸️ Пауза",  "callback_data": "btn_pause"},
        ]]}
        await send_telegram_message(startup_msg, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Startup alert failed: {e}")

    # ── Start Telegram Command Center ───────────────────────────────────
    tg_app = get_telegram_app()
    if tg_app:
        await start_telegram_listener(tg_app)

    # ── Start background tasks ──────────────────────────────────────────
    auto_task    = asyncio.create_task(_automation_loop(),          name="automation_loop")
    ws_task      = asyncio.create_task(monitor_open_positions_ws(), name="ws_position_monitor")
    summary_task = asyncio.create_task(_portfolio_summary_loop(),   name="portfolio_summary")
    ml_train_task = asyncio.create_task(_ml_training_loop(),        name="ml_training_loop")
    paper_closer_task = asyncio.create_task(paper_trade_closer_loop(), name="paper_closer")
    reconciler_task   = asyncio.create_task(reconcile_positions_loop(), name="reconciler")
    heartbeat_task    = asyncio.create_task(_pnl_heartbeat_loop(),      name="pnl_heartbeat")
    
    _background_tasks = [auto_task, ws_task, summary_task, ml_train_task, paper_closer_task, reconciler_task, heartbeat_task]
    
    logger.info("All background tasks started.")
    logger.info("Live Engine: ATR SL | No Hard TP | 2% Trail Activation.")

    yield  # ── Server is running ───────────────────────────────────────

    # ── Graceful Shutdown ───────────────────────────────────────────────
    try:
        shutdown_msg = (
            f"🔴 <b>GROKSNIPER AI — ОСТАНОВЛЕН</b>\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Бот остановлен. До следующего запуска!"
        )
        await send_telegram_message(shutdown_msg)
    except Exception:
        pass

    for task in _background_tasks:
        task.cancel()
    cancel_all_watchers()

    if tg_app:
        await stop_telegram_listener(tg_app)

    for task in _background_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

    await engine.dispose()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(title="GrokSniper AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
