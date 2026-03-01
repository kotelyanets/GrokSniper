"""
engine.py
---------
Core pipeline orchestrator for GrokSniper AI.

`process_news_pipeline` is the single entry point that ties together:
  1. Persisting raw news to PostgreSQL
  2. Sentiment analysis via Grok AI (or mock fallback)
  3. Risk evaluation
  4. Trade execution (live or dry-run)
  5. Persisting the trade result to PostgreSQL
"""

import logging
import os
from decimal import Decimal

from dotenv import load_dotenv

from backend.src.db.database import get_session
from backend.src.db.models import NewsLog, Trade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.grok_ai import (
    SentimentResult,
    analyze_news,
)
from backend.src.services.telegram_bot import send_telegram_message

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk parameters (tune these as the strategy evolves)
# ---------------------------------------------------------------------------
SENTIMENT_THRESHOLD: float = float(os.getenv("SENTIMENT_THRESHOLD", "0.7"))
CONFIDENCE_THRESHOLD: int = int(os.getenv("CONFIDENCE_THRESHOLD", "80"))
TRADE_AMOUNT: float = float(os.getenv("DEFAULT_TRADE_AMOUNT", "0.001"))

# ---------------------------------------------------------------------------
# Module-level exchange instance (shared across pipeline calls)
# ---------------------------------------------------------------------------
_exchange = CryptoExchange()


async def process_news_pipeline(raw_text: str, source: str) -> dict:
    """
    Full news-to-trade pipeline.

    Parameters
    ----------
    raw_text : str
        The raw news article or social-media post body.
    source : str
        Origin label, e.g. "twitter", "reuters", "manual", "rss".

    Returns
    -------
    dict
        A summary of what the pipeline did.
    """
    logger.info("=== Pipeline START | source=%s ===", source)

    # ------------------------------------------------------------------
    # Step 1 — Persist raw news to DB
    # ------------------------------------------------------------------
    async with get_session() as session:
        news_log = NewsLog(source=source, raw_text=raw_text)
        session.add(news_log)
        await session.flush()          # get the UUID without committing yet
        news_log_id = news_log.id
        logger.info("Saved NewsLog id=%s", news_log_id)

    # ------------------------------------------------------------------
    # Step 2 — Sentiment analysis (real or mock)
    # ------------------------------------------------------------------
    sentiment: SentimentResult = await analyze_news(raw_text)
    logger.info(
        "Sentiment | ticker=%s score=%.3f confidence=%d",
        sentiment.ticker,
        sentiment.sentiment_score,
        sentiment.confidence,
    )

    # ------------------------------------------------------------------
    # Step 3 — Update the NewsLog row with the analysis results
    # ------------------------------------------------------------------
    async with get_session() as session:
        news_log = await session.get(NewsLog, news_log_id)
        if news_log:
            news_log.ticker = sentiment.ticker
            news_log.sentiment_score = Decimal(str(sentiment.sentiment_score))
            news_log.confidence = sentiment.confidence

    # ------------------------------------------------------------------
    # Step 4 — Risk gate
    # ------------------------------------------------------------------
    should_trade = (
        sentiment.sentiment_score >= SENTIMENT_THRESHOLD
        and sentiment.confidence >= CONFIDENCE_THRESHOLD
        and sentiment.ticker != "UNKNOWN"
    )

    if not should_trade:
        logger.info(
            "Risk gate: NO TRADE (score=%.3f < %.1f or confidence=%d < %d or ticker=UNKNOWN)",
            sentiment.sentiment_score,
            SENTIMENT_THRESHOLD,
            sentiment.confidence,
            CONFIDENCE_THRESHOLD,
        )
        return {
            "news_log_id": str(news_log_id),
            "ticker": sentiment.ticker,
            "sentiment_score": sentiment.sentiment_score,
            "confidence": sentiment.confidence,
            "trade_placed": False,
            "trade_id": None,
            "trade_status": None,
        }

    # ------------------------------------------------------------------
    # Step 5 — Execute trade
    # ------------------------------------------------------------------
    logger.info(
        "Risk gate: PASSED — placing BUY for %.6f %s", TRADE_AMOUNT, sentiment.ticker
    )
    order = await _exchange.execute_trade(
        ticker=sentiment.ticker,
        action="BUY",
        amount=TRADE_AMOUNT,
    )

    # ------------------------------------------------------------------
    # Step 6 — Persist trade to DB
    # ------------------------------------------------------------------
    async with get_session() as session:
        trade = Trade(
            ticker=sentiment.ticker,
            action="BUY",
            amount=Decimal(str(order["amount"])),
            price=Decimal(str(order["price"])) if order["price"] > 0 else Decimal("1"),
            status="success",
        )
        session.add(trade)
        await session.flush()
        trade_id = trade.id

    logger.info(
        "Trade saved | id=%s status=%s price=%.2f",
        trade_id,
        order["status"],
        order["price"],
    )

    # ------------------------------------------------------------------
    # Step 7 — Telegram notification (fire-and-forget)
    # ------------------------------------------------------------------
    tg_price = float(order["price"])
    tg_message = (
        f"🟢 *SUCCESS: NEW TRADE PLACED*\n\n"
        f"*Ticker:* {sentiment.ticker}\n"
        f"*Action:* BUY\n"
        f"*Price:* ${tg_price:,.2f}\n"
        f"*Grok Score:* {sentiment.sentiment_score:.3f}\n"
        f"*Confidence:* {sentiment.confidence}%"
    )
    await send_telegram_message(tg_message)

    logger.info("=== Pipeline END ===")

    return {
        "news_log_id": str(news_log_id),
        "ticker": sentiment.ticker,
        "sentiment_score": sentiment.sentiment_score,
        "confidence": sentiment.confidence,
        "trade_placed": True,
        "trade_id": str(trade_id),
        "trade_status": order["status"],
    }



@app.post("/api/trigger")
async def trigger_manual_check():
    """
    Принудительный запуск сканирования новостей и анализа.
    Срабатывает при нажатии кнопки 'Test Bot'.
    """
    try:
        from backend.src.services.rss_scraper import fetch_latest_news
        # Вызываем функцию поиска новостей вручную
        new_stories = await fetch_latest_news()
        
        return {
            "status": "success", 
            "message": f"Manual scan complete. Found {len(new_stories)} new articles.",
            "count": len(new_stories)
        }
    except Exception as e:
        logger.error(f"Manual trigger error: {e}")
        return {"status": "error", "message": str(e)}