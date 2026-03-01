"""
crew_analyzer.py
----------------
Orchestrates the 3-agent CrewAI pipeline:
  1. Quant Strategist  → Deep multi-TF chart analysis (80% weight)
  2. Risk/Catalyst Filter → News risk filter (20% weight)
  3. Lead CIO           → Final synthesis → score / confidence / reasoning

Ensures we don't block the FastAPI event loop by offloading the synchronous
Crew kickoff to a thread.
"""

import asyncio
import logging
import re

import json_repair
from pydantic import BaseModel, Field

from crewai import Crew

# ── Agent / Task imports ────────────────────────────────────────────────
from backend.src.agents.strategist import (
    quant_strategist,
    strategist_task,
)
from backend.src.agents.fundamental import (
    analyze_fundamental_task,
    fundamental_analyst,
)
from backend.src.agents.lead_cio import (
    cio_task,
    lead_cio,
)

logger = logging.getLogger(__name__)


class SentimentResult(BaseModel):
    """
    Must exactly match the schema expected by server.py's _automation_loop.
    """
    ticker: str
    sentiment_score: float
    confidence: int
    reason: str = Field(default="No specific reason provided.")


def _extract_ticker(text: str) -> str:
    """
    Very lightweight extraction of the primary ticker from RSS text.
    In a production system you might use a tiny LLM (like GPT-4o-mini),
    but here we use a regex looking for common patterns like $BTC or #ETH.
    Fallback to BTC if nothing is found.
    """
    # Look for $TICKER or #TICKER
    matches = re.findall(r"[\$#]([A-Za-z]{2,10})\b", text)
    if matches:
        # Just grab the first one found
        return matches[0].upper()

    # Fallback to checking if common tickers exist in text
    upper_text = text.upper()
    common = ["BTC", "ETH", "SOL", "DOGE", "XRP", "BNB"]
    for coin in common:
        if coin in upper_text:
            return coin

    # Ultimate fallback
    return "BTC"


async def analyze_news(text: str) -> SentimentResult:
    """
    Phase 37 — 3-Agent Crew Pipeline:
      1) Extracts ticker from RSS text.
      2) Builds a Crew with Strategist (chart), Fundamental (news filter),
         and CIO (synthesis).  The CIO receives context from both.
      3) Offloads Crew kickoff to a thread (non-blocking).
      4) Parses JSON, maps score -100..100 → -1.0..1.0.
    """
    ticker = _extract_ticker(text)
    logger.info(f"[Crew Analyzer] Extracted ticker: {ticker}. Kicking off 3-Agent Crew...")

    # ── Wire up task dependencies ──────────────────────────────────────
    # The CIO task receives the output of both upstream tasks as context.
    cio_task.context = [strategist_task, analyze_fundamental_task]

    crew = Crew(
        agents=[quant_strategist, fundamental_analyst, lead_cio],
        tasks=[strategist_task, analyze_fundamental_task, cio_task],
        verbose=False,  # Keep logs clean in production
    )

    try:
        # ── CRITICAL: Non-blocking Execution ───────────────────────────
        raw_result = await asyncio.to_thread(
            crew.kickoff,
            inputs={"ticker": ticker}
        )

        # ── Robust Parsing ─────────────────────────────────────────────
        # json_repair handles missing quotes, trailing commas, markdown blocks
        parsed = json_repair.loads(str(raw_result))
        
        if not isinstance(parsed, dict):
            raise ValueError(f"Crew returned non-dict JSON: {parsed}")

        # CIO returns int -100 to 100
        raw_score = int(parsed.get("score", 0))
        confidence = int(parsed.get("confidence", 50))
        reasoning = parsed.get("reasoning", "No specific reason provided.")

        # Map -100..100 -> -1.0..1.0
        sentiment_score = raw_score / 100.0

        logger.info(
            f"[Crew Analyzer] CIO Decision for {ticker}: "
            f"score={raw_score} ({sentiment_score:.2f}), conf={confidence}%, "
            f"reason={reasoning[:80]}..."
        )

        return SentimentResult(
            ticker=ticker,
            sentiment_score=sentiment_score,
            confidence=confidence,
            reason=reasoning,
        )

    except Exception as e:
        logger.error(f"[Crew Analyzer] Fallback due to error: {e}")
        # Return a safe neutral fallback so the bot loop doesn't crash
        return SentimentResult(
            ticker=ticker,
            sentiment_score=0.0,
            confidence=0,
            reason=f"Error executing Crew pipeline: {e}"
        )
