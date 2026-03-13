"""
grok_ai.py
----------
Core "Brain" of GrokSniper AI.

Sends news text to the Grok API (OpenAI-compatible) and returns a validated
sentiment analysis result: ticker, sentiment_score, and confidence.
"""

import json
import logging
import os

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GROK_API_KEY: str | None = os.getenv("GROK_API_KEY")
GROK_API_BASE_URL: str = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-4-latest")
GROK_TIMEOUT: float = float(os.getenv("GROK_TIMEOUT_SECONDS", "15"))

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
# Main analysis function
# ---------------------------------------------------------------------------
async def analyze_news(text: str) -> SentimentResult:
    """
    Send *text* to the Grok API and return a validated SentimentResult.
    Falls back to mock data if GROK_API_KEY is missing.
    """
    if not GROK_API_KEY:
        logger.warning("GROK_API_KEY missing — returning MOCK sentiment analysis.")
        return SentimentResult.model_validate(_MOCK_RESULT)

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=GROK_TIMEOUT) as client:
            logger.debug("Sending news text to Grok API (model=%s)", GROK_MODEL)
            response = await client.post(
                f"{GROK_API_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            raw_content: str = data["choices"][0]["message"]["content"]
            parsed: dict = json.loads(raw_content)
            result = SentimentResult.model_validate(parsed)
            logger.info(
                "Grok analysis complete | ticker=%s score=%.3f confidence=%d",
                result.ticker,
                result.sentiment_score,
                result.confidence,
            )
            return result

    except Exception as exc:
        logger.error(f"Grok API call failed or returned invalid JSON: {exc}")
        # Final fallback to mock if API fails in dev mode
        if os.getenv("APP_ENV") != "production":
            logger.info("Dev mode: falling back to MOCK result after API error.")
            return SentimentResult.model_validate(_MOCK_RESULT)
        raise
