"""
routes.py
---------
All FastAPI REST and WebSocket endpoints for GrokSniper AI.

Registers an APIRouter that is mounted on the main `app` in server.py.
All endpoint logic lives here; shared state is imported from state.py.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select, text

from backend.src.api.state import bot_state, dashboard_ws_manager
from backend.src.api.trading_mode import build_trading_mode
from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import AgentDecisionLog, NewsLog, PaperTrade, Trade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.rss_scraper import fetch_latest_news
from backend.src.services.telegram_bot import send_entry_alert, send_exit_alert
from backend.src.services.backtest_service import fetch_historical_data_cached, run_backtest_sim
from backend.src.services.ml_service import get_ml_status
from backend.src.services.monte_carlo_api import run_monte_carlo_web
from backend.src.services.stress_test_api import run_stress_test_web

logger   = logging.getLogger("groksniper.api")
router   = APIRouter()
_exchange = CryptoExchange()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
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
    exchanges_breakdown: dict = {}
    ai_efficiency: float = 0.0
    burn_rate: float = 0.0
    system_health: str = "ONLINE"
    total_invested: float = 0.0
    active_leverage: float = 0.0
    avg_leverage: float = 0.0
    tokens_consumed: int = 0
    ai_analysis_count: int = 0
    api_calls: int = 0
    market_trends: dict = {"4h": "up", "1h": "flat", "15m": "down"}
    risk_radar: dict = {"price": 0.0, "sl": 0.0, "tp": 0.0}


class ManualTradeRequest(BaseModel):
    ticker: str
    amount_usdt: float


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    days_back: int = 30
    initial_balance: float = 1000.0
    hard_stop: float = 0.97
    trailing_activation: float = 1.03
    trailing_distance: float = 0.985
    take_profit: float = 1.08


class MonteCarloRequest(BaseModel):
    n_simulations: int = 10000
    trades_per_sim: int = 200
    initial_balance: float = 10000.0


class StressTestRequest(BaseModel):
    tickers: Optional[list[str]] = None
    days_back: int = 1095
    initial_balance: float = 10000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _decimal_to_float(val) -> float | None:
    return float(val) if isinstance(val, Decimal) else val


# ---------------------------------------------------------------------------
# Read-only endpoints
# ---------------------------------------------------------------------------
@router.get("/api/bot-status", response_model=dict)
async def get_bot_status():
    """Returns the real-time cognitive state of the bot."""
    return {
        **bot_state,
        "trading_mode": build_trading_mode(
            os.getenv("PAPER_TRADE", "False"),
            os.getenv("DRY_RUN", "False"),
            os.getenv("BINANCE_TESTNET", "True"),
        ),
    }


@router.get("/api/positions/live")
async def get_live_positions():
    """
    Returns all open PaperTrade positions enriched with:
      - current live market price (from exchange)
      - unrealised PnL in USDT and %
    Used by the dashboard Open Positions table for real-time price display.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.status == "OPEN")
            )
            trades = result.scalars().all()

        positions = []
        for t in trades:
            try:
                live_price = await _exchange.get_price(t.ticker)
            except Exception:
                live_price = float(t.entry_price)

            entry = float(t.entry_price)
            amount = float(t.size_usdt or 0) / entry if entry > 0 else 0
            if t.action == "LONG":
                unrealised_pnl = (live_price - entry) * amount
                unrealised_pct = ((live_price - entry) / entry * 100) if entry > 0 else 0
            else:
                unrealised_pnl = (entry - live_price) * amount
                unrealised_pct = ((entry - live_price) / entry * 100) if entry > 0 else 0

            positions.append({
                "id":            str(t.id),
                "ticker":        t.ticker,
                "action":        t.action,
                "entry_price":   entry,
                "current_price": live_price,
                "size_usdt":     float(t.size_usdt or 0),
                "stop_loss":     float(t.stop_loss or 0),
                "take_profit":   float(t.take_profit or 0),
                "unrealised_pnl": round(unrealised_pnl, 4),
                "unrealised_pct": round(unrealised_pct, 2),
                "created_at":    t.created_at.isoformat(),
            })

        return {"positions": positions, "count": len(positions)}

    except Exception as e:
        logger.error(f"[live positions] {e}")
        return {"positions": [], "count": 0, "error": str(e)}


@router.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """
    Returns real-time system stats.

    Balance logic:
      LIVE mode  (PAPER_TRADE=False, DRY_RUN=False):
        → total_balance = live CCXT fetch_balance() total USDT value.
          This is the single source of truth. The paper_trades PnL
          accumulator is intentionally IGNORED to prevent desync.
        → pnl_24h = sum of realised PnL stored in the `trades` table.

      PAPER mode (PAPER_TRADE=True):
        → total_balance = INITIAL_EQUITY + cumulative paper_trades PnL.
        → pnl_24h = paper_trades closed PnL.
    """
    is_paper = os.getenv("PAPER_TRADE", "True").lower() == "true"
    is_dry   = os.getenv("DRY_RUN",    "False").lower() == "true"
    is_live  = (not is_paper) and (not is_dry)

    initial_equity = float(os.getenv("INITIAL_EQUITY", "1000.0"))

    # ── Fetch balance from the correct source ─────────────────────────────────
    balance_data = await _exchange.get_balance()
    holdings     = balance_data.get("holdings", [])

    if is_live:
        # LIVE: trust the exchange completely; ignore local ledger
        total_usdt = float(balance_data.get("total_usdt", 0.0))
        logger.debug(f"[Stats/LIVE] CCXT total_usdt={total_usdt:.2f}")
    # Paper mode balance is computed from the DB below after the query

    try:
        async with AsyncSessionLocal() as session:
            trades_count = (await session.execute(text("SELECT count(*) FROM trades"))).scalar() or 0
            news_count   = (await session.execute(text("SELECT count(*) FROM news_logs"))).scalar() or 0

            if is_live:
                # PnL = sum of realised gains/losses recorded in the trades table
                # (entry BUY price vs closing SELL price, stored by execution_engine)
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
                pnl = float(realised_result.scalar() or 0.0)
                # Fallback: if no parent_id linkage, check paper_trades pnl_usdt as proxy
                if pnl == 0.0 and trades_count > 0:
                    paper_pnl_result = await session.execute(
                        text("SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_trades WHERE status = 'CLOSED'")
                    )
                    pnl = float(paper_pnl_result.scalar() or 0.0)
            else:
                # PAPER: balance from initial equity + closed paper_trades PnL
                closed_pnl_result = await session.execute(
                    text("SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_trades WHERE status = 'CLOSED'")
                )
                paper_pnl  = float(closed_pnl_result.scalar() or 0.0)
                total_usdt = initial_equity + paper_pnl
                pnl        = paper_pnl

            # --- Investment Overview (open PaperTrade positions) ---
            open_pt_result = await session.execute(
                text("SELECT COALESCE(SUM(size_usdt), 0), COUNT(*) FROM paper_trades WHERE status = 'OPEN'")
            )
            open_pt_row    = open_pt_result.one()
            total_invested = float(open_pt_row[0] or 0.0)
            active_leverage = int(open_pt_row[1] or 0)

            result      = await session.execute(select(Trade).where(Trade.is_closed == False))
            open_trades = result.scalars().all()

            # Fetch real average AI confidence from logs
            avg_conf_query = await session.execute(text("SELECT AVG(confidence) FROM agent_decision_logs"))
            avg_conf = avg_conf_query.scalar() or 0.875
            actual_ai_efficiency = round(float(avg_conf) * 100, 1)

            # --- REAL MARKET TRENDS ---
            try:
                btc_ta    = await _exchange.get_technical_indicators('BTC', timeframe='1h')
                btc_price = btc_ta['close']
                ema_20    = btc_ta['ema_20']
                rsi       = btc_ta['rsi']

                trend_1h = "up" if btc_price > ema_20 else "down"
                if ema_20 > 0 and abs(btc_price - ema_20) / ema_20 < 0.005:
                    trend_1h = "flat"

                market_trends = {
                    "4h": "up" if btc_price > btc_ta['ema_50'] else "down",
                    "1h": trend_1h,
                    "15m": "up" if rsi > 55 else "down" if rsi < 45 else "flat",
                }

                risk_radar = {"price": btc_price, "sl": btc_price * 0.97, "tp": btc_price * 1.05}
                if open_trades:
                    t = open_trades[0]
                    risk_radar = {
                        "price": btc_price if t.ticker == "BTC" else await _exchange.get_price(t.ticker),
                        "sl":    float(t.stop_loss_price or 0),
                        "tp":    float(t.highest_price) * 1.08 if t.highest_price else 0,
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch market trends: {e}")
                market_trends = {"4h": "up", "1h": "flat", "15m": "down"}
                risk_radar    = {"price": 0.0, "sl": 0.0, "tp": 0.0}

            # Estimate token consumption from logs
            agent_logs_count = (await session.execute(text("SELECT count(*) FROM agent_decision_logs"))).scalar() or 0
            real_tokens    = 72728 + (agent_logs_count * 1500) + (news_count * 450)
            real_burn_rate = 0.59 + ((real_tokens - 72728) * 0.000008)
            real_analyses  = agent_logs_count + int(news_count / 5)
            real_api_calls = 53 + agent_logs_count * 2 + news_count

    except Exception as e:
        logger.error(f"[Stats] DB unavailable: {e}")
        return StatsResponse(
            total_balance=total_usdt if is_live else initial_equity,
            pnl_24h=0.0, total_trades=0,
            signals_processed=0, holdings=holdings, system_health="DB_OFFLINE",
        )

    return StatsResponse(
        total_balance=total_usdt, pnl_24h=pnl,
        total_trades=trades_count, signals_processed=news_count,
        holdings=holdings, exchanges_breakdown=balance_data.get("exchanges_breakdown", {}),
        ai_efficiency=actual_ai_efficiency,
        burn_rate=real_burn_rate, system_health="ONLINE",
        total_invested=total_invested, active_leverage=float(active_leverage),
        avg_leverage=1.0, tokens_consumed=real_tokens,
        ai_analysis_count=real_analyses, api_calls=real_api_calls,
        market_trends=market_trends, risk_radar=risk_radar,
    )


@router.get("/api/news", response_model=list[NewsResponse])
async def get_news():
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(NewsLog).order_by(NewsLog.created_at.desc()).limit(50)
            )
            return [
                NewsResponse(
                    id=str(r.id), source=r.source,
                    raw_text=(r.raw_text[:300] + "...") if len(r.raw_text) > 300 else r.raw_text,
                    ticker=r.ticker,
                    sentiment_score=float(r.sentiment_score) if r.sentiment_score else None,
                    confidence=r.confidence,
                    created_at=r.created_at.isoformat(),
                )
                for r in res.scalars().all()
            ]
    except Exception as e:
        logger.error(f"[News] DB unavailable: {e}")
        return []


@router.get("/api/trades", response_model=list[TradeResponse])
async def get_trades():
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Trade).order_by(Trade.created_at.desc()).limit(50)
            )
            rows = result.scalars().all()
        return [
            TradeResponse(
                id=str(row.id), ticker=row.ticker, action=row.action,
                amount=_decimal_to_float(row.amount),
                price=_decimal_to_float(row.price),
                highest_price=_decimal_to_float(row.highest_price),
                lowest_price=_decimal_to_float(row.lowest_price),
                stop_loss_price=_decimal_to_float(row.stop_loss_price) if hasattr(row, "stop_loss_price") else None,
                position_size_usdt=_decimal_to_float(row.position_size_usdt) if hasattr(row, "position_size_usdt") else None,
                side=row.side, reason=row.reason,
                status="success" if row.status.lower() in {"filled", "completed", "success"} else row.status,
                is_closed=row.is_closed, parent_id=row.parent_id,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error(f"[Trades] DB unavailable: {e}")
        return []


@router.get("/api/health")
async def health():
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass
    return {
        "status":   "ok" if db_ok else "degraded",
        "mode":     "FULL_AUTOMATION",
        "database": "connected" if db_ok else "unreachable",
    }


@router.get("/api/trades/{trade_id}/reasoning")
async def get_trade_reasoning(trade_id: str):
    """Looks up the AI reasoning behind a specific trade. First checks PaperTrade, then falls back to AgentDecisionLog."""
    try:
        async with AsyncSessionLocal() as session:
            trade = (await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )).scalar_one_or_none()
            if not trade:
                return {"reasoning": None, "regime": None, "confidence": None}

            # First, check if we have a direct PaperTrade with the exact reasoning
            # since Phase 2 added direct ai_reasoning mapping
            paper_trade = (await session.execute(
                select(PaperTrade)
                .where(PaperTrade.ticker == trade.ticker)
                .order_by(text(
                    f"ABS(EXTRACT(EPOCH FROM (created_at - TIMESTAMP '{trade.created_at.isoformat()}')))"
                ))
                .limit(1)
            )).scalar_one_or_none()
            
            # If the paper trade was created within ~2 minutes of the real trade
            if paper_trade and abs((paper_trade.created_at - trade.created_at).total_seconds()) < 120:
                reasoning = paper_trade.analysis_report or paper_trade.ai_reasoning
                if reasoning:
                    return {
                        "reasoning": reasoning,
                        "regime": "Dynamic (via Report)",
                        "confidence": 100, # Display max if executed
                        "is_approved": True
                    }

            # Fallback to the overarching agent log if no direct paper trade
            log = (await session.execute(
                select(AgentDecisionLog)
                .where(AgentDecisionLog.ticker == trade.ticker)
                .order_by(text(
                    f"ABS(EXTRACT(EPOCH FROM (created_at - TIMESTAMP '{trade.created_at.isoformat()}')))"
                ))
                .limit(1)
            )).scalar_one_or_none()

            if not log:
                return {"reasoning": "No AI reasoning recorded for this trade.", "regime": "N/A", "confidence": None}

            return {
                "reasoning":  log.cio_reasoning,
                "regime":     log.market_regime,
                "confidence": round(log.confidence * 100) if log.confidence else None,
                "is_approved": log.is_approved,
            }
    except Exception as e:
        logger.error(f"[TradeReasoning] Error: {e}")
        return {"reasoning": "Error fetching reasoning.", "regime": None, "confidence": None}


@router.get("/api/analysis/{ticker}")
async def get_latest_analysis(ticker: str):
    """Fetches the comprehensive analysis report for the most recent paper trade of this ticker."""
    try:
        async with AsyncSessionLocal() as session:
            trade = (await session.execute(
                select(PaperTrade)
                .where(PaperTrade.ticker == ticker)
                .order_by(PaperTrade.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            
            if not trade or not trade.analysis_report:
                return {
                    "ticker": ticker,
                    "report": "Detailed analysis report not available for this trade."
                }
                
            return {
                "ticker": ticker,
                "created_at": trade.created_at.isoformat(),
                "report": trade.analysis_report
            }
    except Exception as e:
        logger.error(f"[AnalysisReport] Error: {e}", exc_info=True)
        return {"ticker": ticker, "report": f"Error fetching report: {e}"}


@router.get("/api/analytics")
async def get_analytics():
    """Returns performance metrics and equity curve from closed PaperTrades."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade)
                .where(PaperTrade.status == "CLOSED")
                .order_by(PaperTrade.created_at.asc())
            )
            trades = result.scalars().all()

        if not trades:
            return {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "equity_curve": []}

        winning = sum(1 for t in trades if t.pnl_usdt is not None and t.pnl_usdt > 0)
        total_pnl = sum(t.pnl_usdt for t in trades if t.pnl_usdt is not None)

        equity_curve, cumulative = [], 0.0
        for t in trades:
            pnl = t.pnl_usdt or 0.0
            cumulative += pnl
            equity_curve.append({
                "date": t.created_at.isoformat(),
                "cumulative_pnl": round(cumulative, 2),
                "trade_pnl": round(pnl, 2),
                "ticker": t.ticker,
            })

        return {
            "total_trades": len(trades),
            "win_rate":     round(winning / len(trades) * 100, 2),
            "total_pnl":    round(total_pnl, 2),
            "equity_curve": equity_curve,
        }
    except Exception as e:
        logger.error(f"[Analytics] Error: {e}")
        return {"error": str(e)}


@router.get("/api/adaptation")
async def get_strategy_adaptation():
    """Returns the real-time strategy adaptation score (0-100) based on trade history."""
    from backend.src.services.memory_manager import get_adaptation_score
    return await get_adaptation_score()


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------
@router.post("/api/reset-paper-test")
async def reset_paper_test():
    """⚠️ Wipes ALL trades, paper_trades, news_logs, and agent_decision_logs."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM trades"))
            await session.execute(text("DELETE FROM paper_trades"))
            await session.execute(text("DELETE FROM news_logs"))
            try:
                await session.execute(text("DELETE FROM agent_decision_logs"))
            except Exception:
                pass
            await session.commit()
        initial_equity = float(os.getenv("INITIAL_EQUITY", "10000.0"))
        logger.warning("🔄 Paper test RESET — virtual balance: $%.2f", initial_equity)
        return {"status": "success", "message": f"Reset. Balance: ${initial_equity:,.2f}", "initial_equity": initial_equity}
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/trigger")
async def trigger_manual_check():
    try:
        new_story = await fetch_latest_news()
        return {"status": "success", "message": "Scanned", "count": 1 if new_story else 0}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/api/buy")
async def manual_buy(req: ManualTradeRequest):
    """Executes a manual MARKET BUY to open a LONG position."""
    try:
        current_price = await _exchange.get_price(req.ticker)
        if current_price <= 0:
            return {"status": "error", "message": "Failed to fetch price"}

        order = await _exchange.place_order(
            ticker=req.ticker, action="BUY", amount=req.amount_usdt / current_price
        )
        if order["status"] == "success":
            stop_loss_price = current_price * 0.97
            async with AsyncSessionLocal() as session:
                new_trade = Trade(
                    ticker=req.ticker, action="BUY",
                    amount=Decimal(str(order["amount"])),
                    price=Decimal(str(order["price"])),
                    highest_price=Decimal(str(order["price"])),
                    stop_loss_price=stop_loss_price,
                    position_size_usdt=req.amount_usdt,
                    status="success", is_closed=False, reason="manual_trade_long",
                )
                session.add(new_trade)
                
                # BRIDGE: Also create a PaperTrade record for analytics
                session.add(PaperTrade(
                    ticker=req.ticker, action="LONG",
                    entry_price=float(order["price"]),
                    size_usdt=req.amount_usdt,
                    stop_loss=stop_loss_price,
                    take_profit=current_price * 1.08, # Default 8% TP for manual
                    status="OPEN", ai_reasoning="Manual Dashboard Entry"
                ))
                await session.commit()
            await send_entry_alert(
                ticker=req.ticker, action="BUY", price=float(order["price"]),
                size=req.amount_usdt, stop_loss=stop_loss_price, confidence=100,
                ai_reasoning="Manual execution via Dashboard.",
                event_type="СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ (MANUAL)",
            )
            return {"status": "success", "order": order}
        return {"status": "error", "message": "Order failed", "details": order}
    except Exception as e:
        logger.error(f"Manual BUY failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/sell")
async def manual_sell(req: ManualTradeRequest):
    """Executes a manual MARKET SELL to open a SHORT position."""
    try:
        current_price = await _exchange.get_price(req.ticker)
        if current_price <= 0:
            return {"status": "error", "message": "Failed to fetch price"}

        order = await _exchange.place_order(
            ticker=req.ticker, action="SELL", amount=req.amount_usdt / current_price
        )
        if order["status"] == "success":
            stop_loss_price = current_price * 1.03
            async with AsyncSessionLocal() as session:
                new_trade = Trade(
                    ticker=req.ticker, action="SELL",
                    amount=Decimal(str(order["amount"])),
                    price=Decimal(str(order["price"])),
                    highest_price=Decimal(str(order["price"])),
                    lowest_price=float(order["price"]),
                    stop_loss_price=stop_loss_price,
                    position_size_usdt=req.amount_usdt,
                    status="success", is_closed=False, side="SHORT",
                    reason="manual_trade_short",
                )
                session.add(new_trade)
                
                # BRIDGE: Also create a PaperTrade record for analytics
                session.add(PaperTrade(
                    ticker=req.ticker, action="SHORT",
                    entry_price=float(order["price"]),
                    size_usdt=req.amount_usdt,
                    stop_loss=stop_loss_price,
                    take_profit=current_price * 0.92, # Default 8% TP for manual short
                    status="OPEN", ai_reasoning="Manual Dashboard Entry"
                ))
                await session.commit()
            await send_entry_alert(
                ticker=req.ticker, action="SELL", price=float(order["price"]),
                size=req.amount_usdt, stop_loss=stop_loss_price, confidence=100,
                ai_reasoning="Manual execution via Dashboard.",
                event_type="СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ (MANUAL)",
            )
            return {"status": "success", "order": order}
        return {"status": "error", "message": "Order failed", "details": order}
    except Exception as e:
        logger.error(f"Manual SELL failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/trades/{trade_id}/close")
async def manual_close(trade_id: str):
    """Manually closes an open (is_closed=False) position."""
    try:
        async with AsyncSessionLocal() as session:
            trade = (await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )).scalar_one_or_none()

            if not trade:
                return {"status": "error", "message": "Trade not found"}
            if trade.is_closed:
                return {"status": "error", "message": "Trade already closed"}
            if trade.action != "BUY":
                return {"status": "error", "message": "Only BUY (open) positions can be closed"}

            ticker       = trade.ticker
            side         = trade.side or "LONG"
            entry_price  = float(trade.price)
            close_amount = float(trade.amount)
            is_paper     = os.getenv("PAPER_TRADE", "False").lower() == "true"

            current_price = await _exchange.get_price(ticker)
            if current_price <= 0:
                current_price = float(trade.highest_price) if side == "LONG" else float(trade.lowest_price)

            close_order = (
                {"status": "success", "price": current_price, "amount": close_amount}
                if is_paper
                else await _exchange.place_order(ticker=ticker, action="BUY" if side == "SHORT" else "SELL", amount=0)
            )
            if close_order["status"] != "success":
                return {"status": "error", "message": "Failed to place closing order"}

            exec_price = float(close_order["price"])
            if side == "SHORT":
                pnl_pct = ((entry_price - exec_price) / entry_price) * 100
                pnl_usd = (entry_price - exec_price) * close_amount
            else:
                pnl_pct = ((exec_price - entry_price) / entry_price) * 100
                pnl_usd = (exec_price - entry_price) * close_amount

            trade.is_closed = True
            session.add(Trade(
                ticker=ticker, action="SELL" if side == "LONG" else "BUY",
                amount=Decimal(str(close_amount)), price=Decimal(str(exec_price)),
                status="success", is_closed=True, parent_id=trade.id, side=side,
            ))
            
            # BRIDGE: Update the PaperTrade record to CLOSED for analytics
            pt_res = await session.execute(
                select(PaperTrade).where(PaperTrade.ticker == ticker, PaperTrade.status == "OPEN").limit(1)
            )
            paper_trade = pt_res.scalar_one_or_none()
            if paper_trade:
                paper_trade.status = "CLOSED"
                paper_trade.exit_price = exec_price
                paper_trade.pnl_usdt = pnl_usd
            else:
                # If no matching open paper trade, create a closed one post-hoc
                session.add(PaperTrade(
                    ticker=ticker, action=side, entry_price=entry_price,
                    exit_price=exec_price, pnl_usdt=pnl_usd, size_usdt=close_amount * entry_price,
                    status="CLOSED", stop_loss=0, take_profit=0, ai_reasoning="Post-hoc closure"
                ))
            await session.commit()

        await send_exit_alert(
            ticker=ticker, exit_label="Manual Close via Dashboard",
            entry_price=entry_price, exit_price=exec_price,
            pnl_usd=pnl_usd, pnl_pct=pnl_pct, side=side, reference_price=current_price,
        )
        return {"status": "success", "message": "Position closed"}
    except Exception as e:
        logger.error(f"Manual CLOSE failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# WebSocket — Dashboard Live Feed
# ---------------------------------------------------------------------------
@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """Long-lived WebSocket for the dashboard. Sends heartbeat every 20s."""
    await dashboard_ws_manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "bot_state", **bot_state}))
        while True:
            await asyncio.sleep(20)
            await websocket.send_text(
                json.dumps({"type": "heartbeat", "ts": datetime.utcnow().isoformat()})
            )
    except WebSocketDisconnect:
        dashboard_ws_manager.disconnect(websocket)
    except asyncio.CancelledError:
        dashboard_ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS Dashboard] Unexpected error: {e}")
        dashboard_ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------
@router.post("/api/backtest")
async def run_backtest_endpoint(req: BacktestRequest):
    """Executes a historical portfolio simulation given dynamic config parameters."""
    try:
        df = await fetch_historical_data_cached(
            symbol=req.symbol, 
            timeframe=req.timeframe, 
            days_back=req.days_back
        )
        if df.empty:
            return {"status": "error", "message": "No historical data found"}
        
        params = {
            "hard_stop": req.hard_stop,
            "trailing_activation": req.trailing_activation,
            "trailing_distance": req.trailing_distance,
            "take_profit": req.take_profit,
        }
        res = run_backtest_sim(df, params, req.initial_balance)
        return {"status": "success", "data": res}
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/monte-carlo")
async def run_monte_carlo_endpoint(req: MonteCarloRequest):
    """Executes a Monte Carlo simulation on historical trades to test Risk of Ruin."""
    try:
        res = run_monte_carlo_web(
            n_simulations=req.n_simulations,
            trades_per_sim=req.trades_per_sim,
            initial_balance=req.initial_balance
        )
        return {"status": "success", "data": res}
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Monte Carlo failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/stress-test")
async def run_stress_test_endpoint(req: StressTestRequest):
    """Executes a 3-year multi-ticker strategy stress test."""
    try:
        res = await run_stress_test_web(
            tickers=req.tickers,
            days_back=req.days_back,
            initial_balance=req.initial_balance
        )
        return {"status": "success", "data": res}
    except Exception as e:
        logger.error(f"Stress Test failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Machine Learning
# ---------------------------------------------------------------------------
@router.get("/api/ml/status")
async def ml_status_endpoint():
    """Returns the internal state and feature importances of the Random Forest model."""
    try:
        data = get_ml_status()
        return data
    except Exception as e:
        logger.error(f"ML Status failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

