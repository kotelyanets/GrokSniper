"""
ai_analyzer.py
--------------
Analyzes crypto news using the real xAI (Grok) API.
Implements a fallback to mock data if the API returns 403 (unauthorized/forbidden).
"""

import json
import logging
import os
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Mock Fallback Data (for testing when API is unavailable)
# ---------------------------------------------------------------------------
_MOCK_SENTIMENT = {
    "ticker": "BTC",
    "sentiment_score": 0.0,
    "confidence": 0,
    "reason": "MOCK DATA — API key not configured. No real sentiment available."
}

class SentimentResult(BaseModel):
    ticker: str
    sentiment_score: float
    confidence: int
    reason: str = Field(default="No specific reason provided.")

async def analyze_news(news_text: str) -> SentimentResult:
    """
    Sends news text to Groq for sentiment analysis.
    Returns a SentimentResult object.
    """
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not found. Using MOCK sentiment.")
        return SentimentResult(**_MOCK_SENTIMENT)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system", 
                "content": "You are an elite crypto quantitative analyst. Analyze the following news and detect the primary crypto assets discussed. "
                           "Return ONLY a JSON object with: ticker (symbol, e.g. ETH), sentiment_score (float -1.0 to 1.0), confidence (int 0-100), "
                           "and reason (a concise 1-2 sentence explanation of why this is good or bad and your expert opinion). "
                           "Be EXTREMELY dynamic with the sentiment_score and confidence based on the gravity and impact of the news. "
                           "Do not use static scores like 0.85 unless exactly appropriate. Use 0.0 only for irrelevant news."
            },
            {"role": "user", "content": news_text}
        ],
        "temperature": 0.1,
        "stream": False
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(GROQ_API_URL, headers=headers, json=payload, timeout=20.0)
            response.raise_for_status()
            data = response.json()
            
            content = data["choices"][0]["message"]["content"]
            # Extract JSON if wrapped in code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(content)
            
            return SentimentResult(
                ticker=parsed.get("ticker", "UNKNOWN").upper(),
                sentiment_score=float(parsed.get("sentiment_score", 0.0)),
                confidence=int(parsed.get("confidence", 0)),
                reason=parsed.get("reason", "No reason provided.")
            )

    except Exception as e:
        logger.error(f"Groq Analysis failed: {e}. Falling back to MOCK.")
        return SentimentResult(**_MOCK_SENTIMENT)
