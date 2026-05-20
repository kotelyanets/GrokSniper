"""
engine.py  —  GrokSniper Pure AI Trading Engine (Phase 8)
=========================================================
Architecture:
    100% AI-driven — Claude Opus is the SOLE decision-maker.
    No hardcoded RSI/MACD/ADX/regime filters.

Pipeline:
    1. Fetch condensed MTF OHLCV (4H + 15m) for ALL tickers
    2. Groq sentiment analysis (FREE) for each ticker
    3. Single BATCH Claude Opus call for ALL tickers at once
    4. Risk gate → execute or skip each decision

Cost Optimization:
    • 1 Claude call per cycle (batch) instead of 5
    • Max 20 candles per ticker sent to Claude
    • Strict JSON output, max 2-sentence reasoning per ticker
"""

import asyncio
import json
import logging
import os
import re
from decimal import Decimal
from typing import Optional

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

from backend.src.db.database import get_session
from backend.src.db.models import NewsLog, Trade
from backend.src.services.exchange import CryptoExchange
from backend.src.services.telegram_bot import send_telegram_message
from backend.src.services.risk_manager import get_dynamic_position_size
from backend.src.services.capital_manager import global_capital_manager

from backend.src.core.agents.quant_analyst import propose_trades
from backend.src.core.agents.risk_guardian import evaluate_proposals
from backend.src.services.memory_manager import fetch_recent_performance_memory

load_dotenv()

logger = logging.getLogger(__name__)

# ── Exchange ─────────────────────────────────────────────────────────────────
_exchange = CryptoExchange()

# ── Risk config ──────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "45"))
MAX_CANDLES = int(os.getenv("MAX_CANDLES", "20"))
ALLOWED_TICKERS = [t.strip() for t in os.getenv(
    "ALLOWED_COINS", "BTC,ETH,SOL,DOGE,XRP"
).split(",")]

# ── Groq (FREE tier — used for sentiment) ────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Claude Opus (PAID — used for quant decisions only) ───────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 0 — BTC Gravity Filter (Safety Net — NOT a trading signal)
# ═══════════════════════════════════════════════════════════════════════════════
# [REMOVED] _get_btc_dump_mode merged into CryptoExchange.is_btc_dumping()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Fetch minimal MTF OHLCV data (token-optimized)
# ═══════════════════════════════════════════════════════════════════════════════
async def _fetch_mtf_condensed_ohlcv(ticker: str) -> tuple[str, dict, object]:
    """
    Fetch MTF data using the centralized Exchange oracle.
    """
    try:
        # Use our centralized indicators service
        indicators = await _exchange.get_technical_indicators(ticker, timeframe='15m')
        
        # Build condensed text for Claude from indicators
        condensed = (
            f"TICKER: {ticker}\n"
            f"15m INDICATORS: RSI={indicators['rsi']:.1f} EMA20={indicators['ema_20']:.1f} "
            f"PRICE: {indicators['close']:.2f} ATR={indicators['atr']:.2f}\n"
            f"MACD={indicators['macd_line']:.2f} SIG={indicators['macd_signal']:.2f}"
        )
        
        # Create a df that's compatible with the chart generator
        # We need more than 1 row for a chart, so let's fetch raw OHLCV for visuals
        # actually for now we'll return the indicators and a minimal df to keep it light
        df_15m = pd.DataFrame([indicators])
        
        return condensed, indicators, df_15m
    except Exception as e:
        logger.error(f"Failed to fetch MTF for {ticker}: {e}")
        return "", {}, None


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Groq Sentiment Analysis (FREE)
# ═══════════════════════════════════════════════════════════════════════════════
async def _groq_sentiment(news_text: str, ticker: str) -> tuple[int, str]:
    """
    Send news to Groq (free) and get a sentiment score [-100, 100]
    and a max 10-word summary.
    Returns (score, summary).
    """
    if not GROQ_API_KEY or not news_text.strip():
        return 0, "No news available"

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=GROQ_API_KEY)
        resp = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a crypto news sentiment scorer. "
                        "Return ONLY valid JSON: {\"score\": <-100 to 100>, \"summary\": \"<max 10 words>\"}\n"
                        "Negative = bearish, Positive = bullish, 0 = neutral."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Ticker: {ticker}\nNews:\n{news_text[:800]}",
                },
            ],
            temperature=0.1,
            max_tokens=60,
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
        score = max(-100, min(100, int(result.get("score", 0))))
        summary = str(result.get("summary", ""))[:80]
        logger.info("Groq sentiment for %s: score=%d summary='%s'", ticker, score, summary)
        return score, summary
    except Exception as e:
        logger.warning("Groq sentiment failed: %s", e)
        return 0, "Sentiment unavailable"


# ═══════════════════════════════════════════════════════════════════════════════
# ROBUST JSON PARSER — Handles markdown wrapping, extra text, etc.
# ═══════════════════════════════════════════════════════════════════════════════
def _extract_json(raw: str) -> object:
    """
    Robustly extract JSON from Claude's response.
    Handles:
      - Raw JSON (array or object)
      - Markdown code fences: ```json ... ```
      - Leading/trailing text: "Here is my analysis:" [...] "Hope this helps!"
      - Mixed content
    Returns parsed Python object (list or dict).
    Raises ValueError if no valid JSON found.
    """
    text = raw.strip()

    # 1. Try direct parse first (fastest path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code fence: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find the outermost JSON array [...] or object {...}
    # Try array first (expected for batch), then object
    for open_char, close_char in [("[", "]"), ("{", "}")]:
        start = text.find(open_char)
        if start == -1:
            continue
        # Find the matching closing bracket by counting nesting
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}...")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Claude Opus BATCH Decision (1 call for ALL tickers)
# ═══════════════════════════════════════════════════════════════════════════════

_BATCH_SYSTEM_PROMPT = (
    "You are the SOLE decision-maker for a crypto trading bot. "
    "There are NO pre-filters or programmatic rules — YOU decide everything.\n\n"
    "RESPONSIBILITIES:\n"
    "1. Analyze the MTF candles (4H + 15m) to determine the market regime for EACH ticker "
    "(trending_up, trending_down, choppy/ranging, distribution, accumulation).\n"
    "2. Identify high-probability setups using price action, support/resistance, "
    "order blocks, liquidity levels, EMA/RSI/MACD signals from the raw data.\n"
    "3. If the market is choppy or conditions are poor for a ticker, output 'HOLD'. "
    "Only output 'LONG' or 'SHORT' if you see a high-probability setup with clear edge.\n"
    "4. Set precise SL and TP based on candle structure (highs/lows/ATR).\n"
    "5. Use the News Sentiment (30% weight) and Technical Data (70% weight).\n\n"
    "RESPOND ONLY with a valid JSON ARRAY — one object per ticker. "
    "No extra text, no markdown, no explanations outside the JSON.\n"
    "Schema for EACH element:\n"
    '{"ticker":"<SYMBOL>", "action":"LONG"|"SHORT"|"HOLD", "confidence":0-100, '
    '"suggested_sl":float, "suggested_tp":float, "position_size_pct":1-25, '
    '"regime":"TRENDING_UP"|"TRENDING_DOWN"|"CHOPPY"|"DISTRIBUTION"|"ACCUMULATION", '
    '"reasoning":"max 2 sentences"}'
)


async def _claude_batch_decision(
    ticker_data: list[dict],
) -> list[dict]:
    """
    Sends ALL tickers in a SINGLE Claude prompt.
    Returns a list of decisions: [{ticker, action, confidence, ...}].

    Args:
        ticker_data: list of dicts with keys:
            - ticker: str
            - condensed: str (OHLCV text)
            - sentiment_score: int
            - sentiment_summary: str
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — cannot run quant analysis")
        return [
            {"ticker": td["ticker"], "action": "HOLD", "confidence": 0,
             "reasoning": "No API key", "suggested_sl": 0, "suggested_tp": 0,
             "position_size_pct": 0, "regime": "UNKNOWN"}
            for td in ticker_data
        ]

    # Build the combined user prompt
    blocks = []
    for td in ticker_data:
        blocks.append(
            f"{'='*60}\n"
            f"=== TICKER: {td['ticker']} ===\n"
            f"{'='*60}\n"
            f"--- TECHNICAL DATA (70% weight) ---\n"
            f"{td['condensed']}\n\n"
            f"--- SENTIMENT (30% weight) ---\n"
            f"Score: {td['sentiment_score']}/100 | Summary: {td['sentiment_summary']}\n"
        )

    user_prompt = (
        "Analyze ALL tickers below and return a JSON ARRAY with one decision per ticker.\n\n"
        + "\n".join(blocks)
        + f"\n\nReturn a JSON array of {len(ticker_data)} objects. JSON only, no extra text."
    )

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            temperature=0.1,
            system=_BATCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = response.content[0].text.strip()
        logger.info("Claude Opus batch raw response length: %d chars", len(raw))
        logger.debug("Claude Opus batch raw: %s", raw[:500])

        # Robust JSON extraction
        parsed = _extract_json(raw)

        # Normalize: if Claude returned a single object, wrap in list
        if isinstance(parsed, dict):
            parsed = [parsed]

        if not isinstance(parsed, list):
            raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

        # Validate and normalize each decision
        decisions = []
        for item in parsed:
            ticker = str(item.get("ticker", "UNKNOWN")).upper()
            action = str(item.get("action", "HOLD")).upper()
            if action not in ("LONG", "SHORT", "HOLD"):
                action = "HOLD"
            confidence = max(0, min(100, int(item.get("confidence", 0))))
            pos_pct = max(1, min(25, int(item.get("position_size_pct", 5))))
            sl = float(item.get("suggested_sl", 0.0))
            tp = float(item.get("suggested_tp", 0.0))
            reasoning = str(item.get("reasoning", ""))[:200]
            regime = str(item.get("regime", "UNKNOWN")).upper()

            decisions.append({
                "ticker": ticker,
                "action": action,
                "confidence": confidence,
                "suggested_sl": sl,
                "suggested_tp": tp,
                "position_size_pct": pos_pct,
                "regime": regime,
                "reasoning": reasoning,
            })

            logger.info(
                "Claude batch: %s → %s (conf=%d, regime=%s) | %s",
                ticker, action, confidence, regime, reasoning,
            )

        return decisions

    except Exception as e:
        logger.error("Claude Opus batch analysis error: %s", e, exc_info=True)
        return [
            {"ticker": td["ticker"], "action": "HOLD", "confidence": 0,
             "suggested_sl": 0, "suggested_tp": 0, "position_size_pct": 0,
             "reasoning": f"Error: {e}", "regime": "UNKNOWN"}
            for td in ticker_data
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Execute a single decision (trade or paper log)
# ═══════════════════════════════════════════════════════════════════════════════
async def _execute_decision(
    decision: dict,
    indicators: dict,
    df_15m,
) -> dict:
    """
    Execute a single trade decision from Claude.
    Handles both paper and real modes.
    Returns a result summary dict.
    """
    ticker = decision["ticker"]
    action = decision["action"]     # LONG or SHORT
    confidence = decision["confidence"]
    pos_pct = decision.get("position_size_pct", 5)
    suggested_sl = decision.get("suggested_sl", 0.0)
    suggested_tp = decision.get("suggested_tp", 0.0)
    quant_reason = decision.get("quant_reasoning", "")
    risk_reason = decision.get("risk_reasoning", "")
    reasoning = f"Quant: {quant_reason} | Risk: {risk_reason}"
    regime = decision.get("regime", "UNKNOWN")

    price = indicators.get("close", 0.0)
    if price <= 0:
        return {"ticker": ticker, "action": "SKIP", "reason": "Invalid price"}

    trade_action = "BUY" if action == "LONG" else "SELL"

    # Position sizing (AI suggestion vs Kelly Criterion)
    initial_equity = float(os.getenv("INITIAL_EQUITY", "10000.0"))
    balance_data = await _exchange.get_balance()
    equity = balance_data.get("total_usdt", initial_equity)
    
    is_paper = os.getenv("DRY_RUN", "False").lower() == "true" or not _exchange._has_keys

    # Get Kelly Criterion baseline maximum size for this balance
    async with get_session() as session:
        kelly_max_usdt, kelly_desc = await get_dynamic_position_size(
            db_session=session, 
            current_balance=equity, 
            paper_trade=is_paper
        )

    # Combine AI confidence explicitly to scale the Kelly max
    # AI pos_pct is usually 1-25% (often 5% default). 
    # Let's say AI suggests 10% allocating size, but Kelly says at most $200.
    # We take the MINIMUM to stay safe.
    ai_usdt = equity * (pos_pct / 100.0)
    trade_usdt = min(ai_usdt, kelly_max_usdt)

    # ── CAPITAL MANAGER EXPOSURE GUARD ─────────────────────────────────────────
    async with get_session() as session:
        is_approved, allowed_usdt, capital_msg = await global_capital_manager.evaluate_trade(
            db_session=session,
            ticker=ticker,
            proposed_action=trade_action,
            proposed_usdt=trade_usdt,
            total_balance=equity,
            is_paper=is_paper
        )

    if not is_approved:
        logger.warning("Capital Manager BLOCKED %s %s: %s", trade_action, ticker, capital_msg)
        return {"ticker": ticker, "action": "SKIP", "reason": f"Capital Manager: {capital_msg}"}

    trade_usdt = allowed_usdt
    amount = trade_usdt / price

    logger.info(
        "FINAL EXECUTION %s %s | Confirmed Size=$%.2f (%.6f @ $%.2f) | conf=%d | %s",
        trade_action, ticker, trade_usdt, amount, price, confidence, capital_msg
    )

    order = await _exchange.execute_trade(
        ticker=ticker,
        action=trade_action,
        amount=amount,
    )

    # Persist trade
    async with get_session() as session:
        new_trade = Trade(
            ticker=ticker,
            action=trade_action,
            amount=Decimal(str(order.get("amount", amount))),
            price=Decimal(str(order.get("price", price))) if order.get("price", 0) > 0 else Decimal(str(price)),
            status="success",
            side=action,  # "LONG" or "SHORT"
            stop_loss_price=float(suggested_sl) if suggested_sl > 0 else None,
            position_size_usdt=float(trade_usdt),
            reason=f"[AI Phase11] {regime} | {reasoning[:400]}",
        )
        session.add(new_trade)
        
        # Compile a detailed analysis report for transparency
        detailed_report = (
            f"=== QUANT ANALYST ===\n{quant_reason}\n\n"
            f"=== RISK GUARDIAN ===\n{risk_reason}\n\n"
            f"=== POSITION SIZING & CAPITAL MANAGEMENT ===\n"
            f"AI Suggested: {pos_pct}% (${ai_usdt:.2f})\n"
            f"Kelly Criterion Limit: ${kelly_max_usdt:.2f}\n"
            f"Capital Manager: {capital_msg}\n"
            f"Final Decision: {kelly_desc} → Size: ${trade_usdt:.2f}\n"
        )
        
        # BRIDGE: Record for analytics if in paper mode
        if is_paper:
            from backend.src.db.models import PaperTrade
            session.add(PaperTrade(
                ticker=ticker,
                action="LONG" if action == "LONG" else "SHORT",
                entry_price=float(new_trade.price),
                size_usdt=float(trade_usdt),
                stop_loss=float(suggested_sl),
                take_profit=float(suggested_tp),
                status="OPEN",
                ai_reasoning=reasoning[:400],
                analysis_report=detailed_report
            ))
        await session.flush()
        trade_id = new_trade.id

    # Telegram notification with chart
    from backend.src.services.telegram_listener import format_trade_open_alert
    tg_caption_html = format_trade_open_alert(
        ticker=ticker, action=action, price=price, size_usdt=trade_usdt,
        confidence=confidence, regime=regime,
        reasoning=f"Quant: {quant_reason} | Risk: {risk_reason}",
        sl=suggested_sl, tp=suggested_tp,
    )

    try:
        from backend.src.services.visuals import generate_trade_chart
        from backend.src.services.telegram_bot import send_photo_alert

        chart_path = generate_trade_chart(ticker, df_15m, action, price, suggested_sl)

        if chart_path and os.path.exists(chart_path):
            await send_photo_alert(chart_path, tg_caption_html, parse_mode="HTML")
            os.remove(chart_path)
        else:
            await send_telegram_message(tg_caption_html, parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to generate/send Telegram chart: %s", e)
        await send_telegram_message(tg_caption_html, parse_mode="HTML")

    return {
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "regime": regime,
        "reasoning": reasoning,
        "suggested_sl": suggested_sl,
        "suggested_tp": suggested_tp,
        "trade_placed": True,
        "trade_id": str(trade_id),
        "trade_usdt": trade_usdt,
        "price": price,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE — Called once per SCAN_INTERVAL
# ═══════════════════════════════════════════════════════════════════════════════
async def scan_all_tickers(latest_news: str = "") -> list[dict]:
    """
    Phase 8: Pure AI pipeline for all tickers.

    1. BTC Gravity Filter (safety only)
    2. Fetch ALL OHLCV data in parallel
    3. Fetch ALL sentiment in parallel (Groq — FREE)
    4. Single batch Claude call for ALL tickers
    5. Execute each actionable decision

    Returns list of result dicts.
    """
    logger.info("═══ PURE AI ENGINE: BATCH SCAN START ═══")

    # ── Step 0: BTC Gravity Filter (safety net only) ─────────────────────
    is_testnet = os.getenv("BINANCE_TESTNET", "").lower() in ("true", "1", "yes")
    if is_testnet:
        logger.info("Testnet mode — skipping BTC dump check (testnet data is unreliable).")
        btc_dump = False
    else:
        btc_dump = await _exchange.is_btc_dumping()
    if btc_dump:
        logger.warning("BTC DUMP MODE — skipping all LONG analysis this cycle.")
        return [{"ticker": t, "action": "SKIP", "reason": "BTC dump mode active", "trade_placed": False}
                for t in ALLOWED_TICKERS]

    # ── Step 1: Fetch OHLCV for all tickers in parallel ──────────────────
    ohlcv_tasks = [_fetch_mtf_condensed_ohlcv(t) for t in ALLOWED_TICKERS]
    ohlcv_results = await asyncio.gather(*ohlcv_tasks, return_exceptions=True)

    # ── Step 2: Fetch sentiment for all tickers in parallel (FREE) ───────
    sentiment_tasks = [_groq_sentiment(latest_news, t) for t in ALLOWED_TICKERS]
    sentiment_results = await asyncio.gather(*sentiment_tasks, return_exceptions=True)

    # ── Step 3: Build batch payload ──────────────────────────────────────
    batch_payload = []
    valid_data = {}  # ticker -> (indicators, df_15m)

    for i, ticker in enumerate(ALLOWED_TICKERS):
        # OHLCV
        ohlcv = ohlcv_results[i]
        if isinstance(ohlcv, Exception) or not ohlcv:
            logger.warning("OHLCV fetch failed for %s: %s", ticker, ohlcv)
            continue
        condensed, indicators, df_15m = ohlcv
        if not condensed:
            logger.warning("No OHLCV data for %s — skipping", ticker)
            continue

        # Sentiment
        sent = sentiment_results[i]
        if isinstance(sent, Exception):
            sent_score, sent_summary = 0, "Sentiment unavailable"
        else:
            sent_score, sent_summary = sent

        batch_payload.append({
            "ticker": ticker,
            "condensed": condensed,
            "sentiment_score": sent_score,
            "sentiment_summary": sent_summary,
        })
        valid_data[ticker] = (indicators, df_15m)

    if not batch_payload:
        logger.warning("No valid OHLCV data for any ticker this cycle.")
        return [{"ticker": t, "action": "SKIP", "reason": "No market data", "trade_placed": False}
                for t in ALLOWED_TICKERS]

    # ── Step 3.5: Fetch Recent AI Memory ─────────────────────────────────
    recent_memory = await fetch_recent_performance_memory(limit=5)
    
    # ── Step 4: Quant Analyst proposes trades ────────────────────────────
    # Map sentiment properly for the Quant Analyst
    sentiment_dict = {
        item["ticker"]: (item["sentiment_score"], item["sentiment_summary"])
        for item in batch_payload
    }
    
    proposed_trades = await propose_trades(batch_payload, sentiment_dict, recent_memory)
    
    # ── Step 4.5: Risk Guardian evaluates proposals ──────────────────────
    if proposed_trades:
        # Extract context if BTC is available
        btc_context = next((td["condensed"] for td in batch_payload if td["ticker"] == "BTC"), "No BTC data")
        final_decisions = await evaluate_proposals(proposed_trades, btc_context, batch_payload, recent_memory)
    else:
        final_decisions = []

    # ── Step 5: Process each decision ────────────────────────────────────
    results = []
    
    # Mark all non-proposed tickers as HOLD
    proposed_tickers = [d.get("ticker") for d in final_decisions]
    for p in batch_payload:
        if p["ticker"] not in proposed_tickers:
            results.append({
                "ticker": p["ticker"],
                "action": "HOLD",
                "confidence": 0,
                "regime": "UNKNOWN",
                "reasoning": "Quant Analyst skipped.",
                "trade_placed": False,
            })

    for decision in final_decisions:
        ticker = decision.get("ticker", "UNKNOWN")
        action = decision.get("proposed_action", "HOLD").upper()
        verdict = decision.get("verdict", "REJECTED").upper()
        confidence = decision.get("confidence", 0)
        regime = decision.get("regime", "UNKNOWN")
        quant_reason = decision.get("quant_reasoning", "")
        risk_reason = decision.get("risk_reasoning", "")
        reasoning = f"Quant: {quant_reason} | Risk: {risk_reason}"

        # ── Diagnostic: log exactly WHY a trade is blocked ───────────────
        block_reasons = []
        if action == "HOLD":
            block_reasons.append(f"action=HOLD")
        if verdict == "REJECTED":
            block_reasons.append(f"verdict=REJECTED (Risk: {risk_reason})")
        if confidence < CONFIDENCE_THRESHOLD:
            block_reasons.append(f"confidence={confidence} < threshold={CONFIDENCE_THRESHOLD}")

        if block_reasons:
            logger.warning(
                "⛔ BLOCKED [%s] %s | Reasons: %s | Quant: %s",
                ticker, action, " + ".join(block_reasons), quant_reason,
            )
            results.append({
                "ticker": ticker,
                "action": "HOLD",
                "confidence": confidence,
                "regime": regime,
                "reasoning": reasoning,
                "trade_placed": False,
            })
            continue

        # Check if we have valid data for this ticker
        if ticker not in valid_data:
            logger.warning("Agents approved %s but no OHLCV data available", ticker)
            results.append({"ticker": ticker, "action": "SKIP", "reason": "No data", "trade_placed": False})
            continue
        
        # Override the action key format for execute_decision compatibility
        decision["action"] = action

        indicators, df_15m = valid_data[ticker]

        # Persist raw news for the first actionable signal
        if latest_news.strip():
            try:
                async with get_session() as session:
                    news_log = NewsLog(source="auto_scan", raw_text=latest_news[:500],
                                      ticker=ticker,
                                      sentiment_score=Decimal(str(decision.get("confidence", 0) / 100.0)),
                                      confidence=confidence)
                    session.add(news_log)
            except Exception as e:
                logger.warning("News log persist failed: %s", e)

        # Execute!
        try:
            result = await _execute_decision(decision, indicators, df_15m)
            results.append(result)
        except Exception as e:
            logger.error("Execution error for %s: %s", ticker, e, exc_info=True)
            results.append({"ticker": ticker, "action": "ERROR", "reason": str(e), "trade_placed": False})

    # ── Summary log ──────────────────────────────────────────────────────
    executed = [r["ticker"] for r in results if r.get("trade_placed")]
    held = [r["ticker"] for r in results if r.get("action") == "HOLD"]
    logger.info(
        "═══ PURE AI ENGINE CYCLE DONE | Executed: %s | Held: %s ═══",
        executed or "none", held or "none",
    )

    return results


# Legacy compatibility — keep run_hybrid_analysis as alias
async def run_hybrid_analysis(
    ticker: str,
    news_text: str = "",
    source: str = "scanner",
    btc_dump_mode: bool = False,
) -> dict:
    """Legacy wrapper — redirects to scan_all_tickers for a single ticker."""
    logger.info("Legacy run_hybrid_analysis called for %s — redirecting to batch pipeline", ticker)
    results = await scan_all_tickers(latest_news=news_text)
    for r in results:
        if r.get("ticker") == ticker:
            return r
    return {"ticker": ticker, "action": "HOLD", "confidence": 0, "reasoning": "Not found in batch", "trade_placed": False}