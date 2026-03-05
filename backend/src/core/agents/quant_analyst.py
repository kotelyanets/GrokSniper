import os
import json
import logging
from anthropic import AsyncAnthropic

logger = logging.getLogger("groksniper.agents.quant")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-opus-20240229")
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "60"))

QUANT_SYSTEM_PROMPT = """You are the Lead Quant Analyst for a crypto hedge fund.
Your SOLE job is to find aggressive, high-Risk/Reward trade setups.
Look for: Breakouts, liquidity grabs, strong momentum (EMA alignment), and MTF confluence.
Do NOT worry about macro liquidity or BTC context—your colleague (The Risk Guardian) will handle that.

Analyze the provided 4H and 15m OHLCV data.
For each ticker, if the technical setup is strong enough, propose a 'LONG' or 'SHORT'.
If the chart is garbage or choppy, output 'HOLD'.

RESPOND ONLY with valid JSON:
[
  {
    "ticker": "BTC",
    "proposed_action": "LONG"|"SHORT"|"HOLD",
    "confidence": 0-100,
    "suggested_sl": float,
    "suggested_tp": float,
    "position_size_pct": 1-100,
    "quant_reasoning": "max 2 sentences explaining the technical setup"
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
        except:
            pass

    raise ValueError("Could not extract valid JSON array from Quant LLM response.")

async def propose_trades(
    all_ticker_data: list[dict], 
    sentiment_scores: dict[str, tuple[int, str]],
    recent_memory: str = ""
) -> list[dict]:
    """
    Calls the Quant Analyst to propose trades based solely on technicals, sentiment, and memory.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("No ANTHROPIC_API_KEY found.")
        return []

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    
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
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            temperature=0.3,
            system=QUANT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )
        raw = response.content[0].text.strip()
        parsed = _extract_json_quant(raw)
        
        # Filter for only actionable trades meeting confidence
        proposals = []
        for prop in parsed:
            action = prop.get("proposed_action", "HOLD").upper()
            if action not in ("LONG", "SHORT", "HOLD"):
                action = "HOLD"
            conf = int(prop.get("confidence", 0))
            
            if action != "HOLD" and conf >= CONFIDENCE_THRESHOLD:
                proposals.append(prop)
            else:
                logger.info("Quant rejected %s: action=%s, conf=%d", prop.get("ticker", "Unknown"), action, conf)
                
        return proposals
        
    except Exception as e:
        logger.error("Quant Analyst Error: %s", e)
        return []
