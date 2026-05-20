"""
grok_ai.py
----------
Core "Brain" of GrokSniper AI.

Sends news text to the Groq API (using llama-3.3-70b-versatile) and returns a validated
sentiment analysis result: ticker, sentiment_score, and confidence.
Falls back to local FinBERT sentiment analysis if the API fails or is not configured.
"""

import json
import logging
import os
import re

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from groq import AsyncGroq
from backend.src.services.finbert_analyzer import analyze_news_sentiment

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GROQ_MODEL: str = "llama-3.3-70b-versatile"
GROQ_TIMEOUT: float = float(os.getenv("GROQ_TIMEOUT_SECONDS", "15"))

# ---------------------------------------------------------------------------
# Mock Data (used if API key is missing or call fails in dev)
# ---------------------------------------------------------------------------
_MOCK_RESULT = {
    "ticker": "BTC",
    "sentiment_score": 0.0,
    "confidence": 0
}

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """
You are an elite quantitative crypto financial analyst with deep expertise in
market microstructure, on-chain data, and news-driven price action.

Your ONLY job is to analyse a piece of news or social-media text and determine:
1. The PRIMARY crypto asset ticker it refers to (e.g. BTC, ETH, SOL).
2. The sentiment direction and magnitude on a scale from -1.0 (extremely bearish)
   to +1.0 (extremely bullish), with 0.0 representing neutral.
3. Your confidence in that assessment as a whole-number percentage (0–100).

Rules you MUST follow:
- Output ONLY a single, minified, valid JSON object — no markdown, no prose.
- The JSON schema is exactly: {"ticker": string, "sentiment_score": float, "confidence": int}
- sentiment_score must be a float with at most 3 decimal places.
- confidence must be an integer from 0 to 100.
- If you cannot identify a clear crypto ticker, use "UNKNOWN" for ticker.
- If the text is clearly irrelevant to crypto markets, set sentiment_score to 0.0
  and confidence to 0.
- Never include explanations or extra keys in your output.

Example outputs:
{"ticker": "BTC", "sentiment_score": 0.87, "confidence": 92}
{"ticker": "ETH", "sentiment_score": -0.65, "confidence": 78}
{"ticker": "UNKNOWN", "sentiment_score": 0.0, "confidence": 0}
""".strip()


# ---------------------------------------------------------------------------
# Pydantic response model
# ---------------------------------------------------------------------------
class SentimentResult(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    confidence: int = Field(..., ge=0, le=100)

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("sentiment_score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 3)


# ---------------------------------------------------------------------------
# Helper function to extract ticker
# ---------------------------------------------------------------------------
def _extract_ticker(text: str) -> str:
    """
    Extract the primary crypto asset ticker from news text.
    """
    matches = re.findall(r"[\$#]([A-Za-z]{2,10})\b", text)
    if matches:
        return matches[0].upper()

    # Fallback to checking if common tickers exist in text
    upper_text = text.upper()
    common = ["BTC", "ETH", "SOL", "DOGE", "XRP", "BNB"]
    for coin in common:
        if coin in upper_text:
            return coin

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# FinBERT Fallback
# ---------------------------------------------------------------------------
async def _finbert_fallback(text: str, error_reason: str) -> SentimentResult:
    """
    Helper function to run FinBERT news analysis and convert it to SentimentResult.
    """
    ticker = _extract_ticker(text)
    logger.info(f"[FinBERT Fallback] Triggered because of: {error_reason}")
    try:
        finbert_res = await analyze_news_sentiment(text)
        label = finbert_res.get("label", "neutral")
        score = finbert_res.get("score", 0.0)

        # Map label and score to sentiment_score
        if label == "positive":
            sentiment_score = score
        elif label == "negative":
            sentiment_score = -score
        else:
            sentiment_score = 0.0

        confidence = int(score * 100)

        result = SentimentResult(
            ticker=ticker,
            sentiment_score=sentiment_score,
            confidence=confidence
        )

        logger.info(
            "[FinBERT Fallback] Analysis complete | ticker=%s score=%.3f confidence=%d",
            result.ticker,
            result.sentiment_score,
            result.confidence,
        )
        return result
    except Exception as e:
        logger.error(f"[FinBERT Fallback] Classifier failed: {e}")
        return SentimentResult(
            ticker=ticker,
            sentiment_score=0.0,
            confidence=0
        )


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------
async def analyze_news(text: str) -> SentimentResult:
    """
    Send *text* to the Groq API and return a validated SentimentResult.
    Falls back to FinBERT local model if the API call fails or GROQ_API_KEY is missing.
    """
    if not GROQ_API_KEY:
        return await _finbert_fallback(text, "GROQ_API_KEY is missing or empty")

    client = AsyncGroq(api_key=GROQ_API_KEY)

    try:
        logger.debug("Sending news text to Groq API (model=%s)", GROQ_MODEL)
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=128,
            response_format={"type": "json_object"},
            timeout=GROQ_TIMEOUT
        )
        raw_content: str = response.choices[0].message.content
        parsed: dict = json.loads(raw_content)
        result = SentimentResult.model_validate(parsed)
        logger.info(
            "Groq analysis complete | ticker=%s score=%.3f confidence=%d",
            result.ticker,
            result.sentiment_score,
            result.confidence,
        )
        return result

    except Exception as exc:
        return await _finbert_fallback(text, f"Groq API error: {exc}")
