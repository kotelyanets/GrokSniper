import os
import json
import logging
from groq import AsyncGroq

logger = logging.getLogger("groksniper.agents.quant")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "60"))

QUANT_SYSTEM_PROMPT = """You are the Lead Quant Analyst for a crypto hedge fund.
Your SOLE job is to find aggressive, high-Risk/Reward trade setups.
Look for: Breakouts, liquidity grabs, strong momentum (EMA/MACD alignment), volatility expansions (Bollinger Bands), and MTF confluence (1D, 4H, 15m).
Do NOT worry about macro liquidity or BTC context—your colleague (The Risk Guardian) will handle that.

Analyze the provided Daily, 4H, and 15m OHLCV data, along with RSI, EMAs, MACD, and Bollinger Bands.
For each ticker, if the technical setup shows ANY directional bias, propose 'LONG' or 'SHORT'.
Only output 'HOLD' if the chart is truly directionless/choppy with no identifiable setup.

IMPORTANT POSITION SIZING: Dynamically calculate your `position_size_pct` based on the provided ATR (Average True Range) volatility. If ATR is high (market is highly volatile, requiring wide stops), reduce your position size % to limit absolute dollar risk. If ATR is low (tight stops), you can increase size.

CRITICAL: ADAPTATION MEMORY & PATTERN RECOGNITION
You will receive a "STRATEGY ADAPTATION MEMORY" block. It contains your historical win rates and specific PATTERN RECOGNITION directives (e.g., "AVOID BTC LONG", "AGGRESSIVE ON ETH SHORT").
You MUST obey these directives. If a pattern is marked as a historical loser, you MUST require an exceptionally high confidence (>85) to propose it, or otherwise propose HOLD. If a pattern is a proven winner, you may propose it more aggressively.

IMPORTANT: You are in a forward test / paper trading environment.
It is BETTER to propose a trade and learn from it than to sit idle holding cash.
Be aggressive — the Risk Guardian will filter you if needed.

RESPOND ONLY with valid JSON:
[
  {
    "ticker": "BTC",
    "proposed_action": "LONG"|"SHORT"|"HOLD",
    "confidence": 0-100,
    "suggested_sl": float,
    "suggested_tp": float,
    "position_size_pct": 1-100,
    "quant_reasoning": "max 2 sentences explaining the technical setup and why you chose this position size based on ATR/Volatility"
  }
]
"""

def _extract_json_quant(raw: str) -> list[dict]:
    import re
    text = raw.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1).strip())
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass

    arr_match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError("Could not extract valid JSON array from Quant LLM response.")

async def propose_trades(
    all_ticker_data: list[dict], 
    sentiment_scores: dict[str, tuple[int, str]],
    recent_memory: str = ""
) -> list[dict]:
    """
    Calls the Quant Analyst to propose trades based solely on technicals, sentiment, and memory.
    No confidence filtering here — the engine handles the single confidence gate.
    """
    if not GROQ_API_KEY:
        logger.error("No GROQ_API_KEY found.")
        return []

    client = AsyncGroq(api_key=GROQ_API_KEY)
    
    # Construct the payload
    prompt_lines = []
    
    if recent_memory:
        prompt_lines.append(recent_memory)
        prompt_lines.append("\n==================================")
        
    prompt_lines.append("--- QUANTITATIVE DATA FEED ---")
    
    for td in all_ticker_data:
        t = td["ticker"]
        # Basic sentiment
        s_score, s_sum = sentiment_scores.get(t, (0, "No news"))
        prompt_lines.append(f"\n{td['condensed']}")
        prompt_lines.append(f"SENTIMENT: Score={s_score} ({s_sum})")
    
    user_prompt = "\n".join(prompt_lines)

    try:
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": QUANT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        parsed = _extract_json_quant(raw)
        
        # Pass ALL proposals through — the engine handles the confidence gate
        proposals = []
        for prop in parsed:
            action = prop.get("proposed_action", "HOLD").upper()
            if action not in ("LONG", "SHORT", "HOLD"):
                action = "HOLD"
            conf = int(prop.get("confidence", 0))
            
            if action != "HOLD":
                proposals.append(prop)
                logger.info("Quant PROPOSED %s: action=%s, conf=%d", prop.get("ticker", "Unknown"), action, conf)
            else:
                logger.info("Quant held %s: action=%s, conf=%d", prop.get("ticker", "Unknown"), action, conf)
                
        return proposals
        
    except Exception as e:
        logger.error("Quant Analyst Error: %s", e)
        return []

