"""
ml_bootcamp.py
--------------
Phase 28.1: Groq-less High-Speed ML Bootcamp.

Fetches thousands of historical crypto news articles from CryptoCompare,
matches each one to a Binance 1h forward return via the PUBLIC klines API
(no authentication needed), and bulk-saves raw_text + actual_return to DB.

No LLM calls, no API keys — runs at near-network-limit speed.

Run from the project root:
    python -m backend.src.scripts.ml_bootcamp

Environment variables (inherited from .env):
    DATABASE_URL  — PostgreSQL async URL (required)
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt.async_support as ccxt
import httpx
from dotenv import load_dotenv
from sqlalchemy import select

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # …/sniper_bot
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import NewsLog

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("groksniper.bootcamp")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

# Bootcamp settings
RETRAIN_EVERY : int = 100    # retrain model after every N new saved samples
MAX_PAGES     : int = 500    # maximum pagination pages (~50 articles each = up to 25k articles)
SOURCE_LABEL  : str = "bootcamp_cryptocompare"

# Known tradeable tickers — articles that mention none of these get a generic
# "CRYPTO" label so we still save the text (useful training signal).
KNOWN_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "SHIB", "DOT", "MATIC", "LINK", "LTC", "TRX", "UNI", "NEAR",
    "FTM", "APT", "ARB", "OP", "ATOM", "ICP", "FIL", "VET",
}


# ---------------------------------------------------------------------------
# Keyword → ticker heuristic  (no LLM needed)
# ---------------------------------------------------------------------------
def _extract_ticker_heuristic(text: str) -> str:
    """
    Cheap, fast keyword scan over the text to pick the most prominent ticker.
    Returns the ticker string or 'CRYPTO' if nothing is found.
    """
    upper = text.upper()
    # Score each ticker by number of mentions
    best_ticker = "CRYPTO"
    best_count  = 0
    for ticker in KNOWN_TICKERS:
        count = upper.count(ticker)
        if count > best_count:
            best_count  = count
            best_ticker = ticker
    return best_ticker


# ---------------------------------------------------------------------------
# Shared Binance exchange client (created once, reused for all OHLCV calls)
# ---------------------------------------------------------------------------
# Using a single instance avoids repeated TCP handshakes and prevents the
# per-article create/close pattern from triggering Binance's rate limiter.
_binance: ccxt.binance | None = None


async def _get_exchange() -> ccxt.binance:
    """Returns the shared public Binance CCXT instance, initialising it on first call."""
    global _binance
    if _binance is None:
        _binance = ccxt.binance({"enableRateLimit": True})
        _binance.set_sandbox_mode(False)   # mainnet only — testnet has no historical data
    return _binance


# ---------------------------------------------------------------------------
# Binance historical OHLCV → 1h forward return
# ---------------------------------------------------------------------------
async def _fetch_actual_return(ticker: str, article_ts_ms: int) -> float | None:
    """
    Fetches the 1h Binance candle at *article_ts_ms* via the public klines
    endpoint (no API keys needed).  Returns (close-open)/open or None.
    """
    if ticker in ("CRYPTO", "UNKNOWN", "NONE", ""):
        return None   # no tradeable Binance symbol for generic labels

    symbol = f"{ticker}/USDT"

    try:
        exch  = await _get_exchange()
        ohlcv = await exch.fetch_ohlcv(symbol, "1h", since=article_ts_ms, limit=2)

        if not ohlcv:
            logger.warning(f"OHLCV: empty response for {symbol} at ts={article_ts_ms}")
            return None

        open_p  = float(ohlcv[0][1])
        close_p = float(ohlcv[0][4])

        if open_p <= 0:
            return None

        return round((close_p - open_p) / open_p, 6)

    except (ccxt.BadSymbol, ccxt.ExchangeError) as exc:
        # Symbol genuinely doesn't exist on Binance (e.g. obscure alt-coin)
        logger.debug(f"OHLCV: {symbol} not available → {exc}")
        return None
    except ccxt.NetworkError as exc:
        logger.warning(f"OHLCV: network error fetching {symbol} → {exc}")
        return None
    except Exception as exc:
        logger.warning(f"OHLCV: unexpected error for {symbol} → {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Binance micro-candles → pre-news features (NO data leakage)
# ---------------------------------------------------------------------------
async def _fetch_micro_candles(ticker: str, article_ts_ms: int) -> dict | None:
    """
    Fetches the 1 hour of 5m and 15m candles BEFORE the article timestamp.
    Returns {"5m_volatility": float, "15m_volume_spike": float} or None.

    This is the pre-news market context — exactly the data available at
    decision time, avoiding data leakage.
    """
    if ticker in ("CRYPTO", "UNKNOWN", "NONE", ""):
        return None

    symbol = f"{ticker}/USDT"
    since_ms = article_ts_ms - 3_600_000  # 1 hour before article

    try:
        exch = await _get_exchange()

        # 5-minute candles: 12 candles = 1 hour
        ohlcv_5m = await exch.fetch_ohlcv(symbol, "5m", since=since_ms, limit=12)
        # 15-minute candles: 4 candles = 1 hour
        ohlcv_15m = await exch.fetch_ohlcv(symbol, "15m", since=since_ms, limit=4)

        if not ohlcv_5m or not ohlcv_15m:
            return None

        # 5m_volatility: average (high - low) across pre-news 5m candles
        volatilities = [float(c[2]) - float(c[3]) for c in ohlcv_5m]  # high - low
        avg_5m_volatility = sum(volatilities) / len(volatilities) if volatilities else 0.0

        # 15m_volume_spike: max volume / mean volume (spike detection)
        volumes_15m = [float(c[5]) for c in ohlcv_15m]
        mean_vol = sum(volumes_15m) / len(volumes_15m) if volumes_15m else 1.0
        max_vol  = max(volumes_15m) if volumes_15m else 0.0
        volume_spike = round(max_vol / mean_vol, 4) if mean_vol > 0 else 1.0

        return {
            "5m_volatility": round(avg_5m_volatility, 6),
            "15m_volume_spike": volume_spike,
        }

    except (ccxt.BadSymbol, ccxt.ExchangeError):
        return None
    except ccxt.NetworkError as exc:
        logger.debug(f"Micro-candles: network error for {symbol} → {exc}")
        return None
    except Exception as exc:
        logger.debug(f"Micro-candles: error for {symbol} → {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def _is_duplicate(session, external_id: str) -> bool:
    source_key = f"{SOURCE_LABEL}:{external_id}"
    stmt = select(NewsLog.id).where(NewsLog.source == source_key).limit(1)
    result = await session.execute(stmt)
    return result.first() is not None


async def _save_log(
    session,
    external_id  : str,
    raw_text     : str,
    ticker       : str,
    actual_return: float | None,
    article_time : datetime,
    micro_features: dict | None = None,
) -> None:
    """
    Inserts a NewsLog row.

    - sentiment_score is stored as 0.0 (neutral placeholder) so the column
      constraint is satisfied.  The ML pipeline will NOT use this field.
    - actual_return is embedded into raw_text as a structured tag so the
      upgraded model.py can extract it during training if needed; it is also
      readable via grep for debugging.
    - micro_features is stored as a JSON string for 5m/15m market context.
    """
    source_key = f"{SOURCE_LABEL}:{external_id}"

    if actual_return is not None:
        annotated = f"[RETURN:{actual_return:+.6f}] {raw_text}"
    else:
        annotated = raw_text

    log = NewsLog(
        source          = source_key,
        raw_text        = annotated[:8000],
        ticker          = ticker,
        sentiment_score = 0.0,   # placeholder — model uses raw_text only
        confidence      = 0,     # placeholder
        micro_features  = json.dumps(micro_features) if micro_features else None,
        created_at      = article_time,
    )
    session.add(log)
    await session.commit()


# ---------------------------------------------------------------------------
# Retraining trigger
# ---------------------------------------------------------------------------
async def _retrain_model(total_count: int) -> None:
    logger.info(f"Bootcamp: {total_count} articles processed — triggering model retrain…")
    try:
        from backend.src.ml.model import train_model as _train
        success = await _train()

        if success:
            try:
                import joblib
                model_path = Path(__file__).resolve().parents[2] / "ml" / "saved_model.pkl"
                if model_path.exists():
                    bundle  = joblib.load(model_path)
                    model   = bundle.get("model")
                    r2      = getattr(model, "oob_score_", None)
                    r2_str  = f"{r2:.4f}" if r2 is not None else "N/A"
                    logger.info(
                        f"Bootcamp: Processed {total_count} articles. "
                        f"Model retrained. R² Score: {r2_str}"
                    )
            except Exception as e:
                logger.debug(f"Score readback error: {e}")
                logger.info(f"Bootcamp: Processed {total_count} articles. Model retrained.")
        else:
            logger.warning(
                f"Bootcamp: Retrain skipped — need ≥50 samples "
                f"with actual_return. Current count: {total_count}"
            )
    except Exception as exc:
        logger.error(f"Bootcamp: Retrain failed: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# CryptoCompare → one page of news
# ---------------------------------------------------------------------------
async def _fetch_news_page(
    client   : httpx.AsyncClient,
    before_ts: int | None,
) -> tuple[list[dict], int | None]:
    params: dict = {"lang": "EN", "extraParams": "GrokSniperBootcamp"}
    if before_ts is not None:
        params["lTs"] = before_ts

    try:
        resp = await client.get(CRYPTOCOMPARE_NEWS_URL, params=params, timeout=30.0)
        resp.raise_for_status()
        data     = resp.json()
        articles = data.get("Data", [])
        if not articles:
            return [], None
        oldest = min(int(a.get("published_on", 0)) for a in articles)
        return articles, oldest
    except Exception as exc:
        logger.error(f"CryptoCompare fetch error: {exc}")
        return [], None


# ---------------------------------------------------------------------------
# Main bootcamp loop
# ---------------------------------------------------------------------------
async def run_bootcamp() -> None:
    logger.info("=" * 60)
    logger.info("  GrokSniper ML Bootcamp v2 — Pure NLP (No Groq)")
    logger.info("=" * 60)
    logger.info("  Binance OHLCV        : public endpoint (no keys needed)")
    logger.info(f"  Retrain every        : {RETRAIN_EVERY} articles")
    logger.info(f"  Max pages            : {MAX_PAGES}  (~{MAX_PAGES * 50:,} articles)")
    logger.info("=" * 60)

    total_processed = 0
    total_skipped   = 0
    next_retrain_at = RETRAIN_EVERY
    before_ts       : int | None = None

    async with httpx.AsyncClient() as http:
        for page_num in range(1, MAX_PAGES + 1):
            logger.info(
                f"── Page {page_num}/{MAX_PAGES} │ "
                f"saved={total_processed} │ skipped={total_skipped}"
            )

            articles, oldest_ts = await _fetch_news_page(http, before_ts)

            if not articles:
                logger.info("No more articles — bootcamp complete.")
                break

            async with AsyncSessionLocal() as session:
                for article in articles:
                    external_id   = str(article.get("id", ""))
                    title         = article.get("title", "").strip()
                    body          = article.get("body", "").strip()
                    published_on  = int(article.get("published_on", 0))

                    if not external_id or not title:
                        total_skipped += 1
                        continue

                    # ── Duplicate check ────────────────────────────────────
                    if await _is_duplicate(session, external_id):
                        total_skipped += 1
                        continue

                    # ── Combine text ───────────────────────────────────────
                    combined_text = f"{title}\n\n{body[:3000]}" if body else title

                    # ── Fast heuristic ticker extraction (no LLM) ──────────
                    ticker = _extract_ticker_heuristic(combined_text)

                    # ── Binance 1h forward return ──────────────────────────
                    article_ts_ms = published_on * 1000
                    actual_return = await _fetch_actual_return(ticker, article_ts_ms)

                    # ── Pre-news micro-candles (5m + 15m) ──────────────────
                    micro = await _fetch_micro_candles(ticker, article_ts_ms)

                    # ── Save to DB ─────────────────────────────────────────
                    article_time = datetime.fromtimestamp(published_on, tz=timezone.utc)
                    await _save_log(
                        session        = session,
                        external_id    = external_id,
                        raw_text       = combined_text,
                        ticker         = ticker,
                        actual_return  = actual_return,
                        article_time   = article_time,
                        micro_features = micro,
                    )

                    total_processed += 1

                    ret_str   = f"{actual_return:+.4f}" if actual_return is not None else "N/A"
                    micro_str = f"vol5m={micro['5m_volatility']:.4f} vspk15m={micro['15m_volume_spike']:.2f}" if micro else "no-micro"
                    logger.info(
                        f"[{total_processed:>5}] Saved │ {ticker:<6} │ return={ret_str} │ "
                        f"{micro_str} │ {title[:50]}"
                    )

                    # ── Auto-retrain checkpoint ────────────────────────────
                    if total_processed >= next_retrain_at:
                        await _retrain_model(total_processed)
                        next_retrain_at += RETRAIN_EVERY

            # Advance pagination cursor
            if not oldest_ts:
                logger.info("Pagination boundary reached — stopping.")
                break

            before_ts = oldest_ts
            await asyncio.sleep(0.2)   # tiny pause between page fetches — not rate-limited

    # ── Final summary ──────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"  Bootcamp finished!")
    logger.info(f"  Articles saved   : {total_processed}")
    logger.info(f"  Articles skipped : {total_skipped}")
    logger.info("=" * 60)

    # Final retrain for any remainder
    remainder = total_processed % RETRAIN_EVERY
    if total_processed > 0 and remainder != 0:
        logger.info(f"Final retrain with {remainder} remaining new articles…")
        await _retrain_model(total_processed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(run_bootcamp())
