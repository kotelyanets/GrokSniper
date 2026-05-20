import os
import json
import logging
from groq import AsyncGroq

logger = logging.getLogger("groksniper.agents.risk")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

RISK_SYSTEM_PROMPT = """You are the Chief Risk Officer (Risk Guardian) of a crypto hedge fund.
The Quant Analyst has forwarded you several high-probability trade proposals.
Your job is to PROTECT CAPITAL. You evaluate the macro picture, BTC structure, and asset-specific risk.
You are looking for REASONS TO REJECT these trades. Example risks:
- Buying an altcoin when BTC is highly distribution/choppy.
- Taking a SHORT when sentiment is overwhelmingly positive.
- Too high of a position size recommendation.

For EACH proposed trade, provide a verdict: APPROVED or REJECTED.
If you REJECT, supply a short reason. If APPROVED, supply your risk blessing.

RESPOND ONLY with valid JSON:
[
  {
    "ticker": "BTC",
    "verdict": "APPROVED" | "REJECTED",
    "final_position_size_pct": 1-100,  # You can adjust the Quant's size down if risky, or keep same.
    "risk_reasoning": "max 2 sentences explaining why it is safe or why it is blocked"
  }
]
"""

def _extract_json_risk(raw: str) -> list[dict]:
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

    raise ValueError("Could not extract valid JSON array from Risk LLM response.")

async def evaluate_proposals(
    proposals: list[dict], 
    btc_context: str, 
    all_ticker_data: list[dict],
    recent_memory: str = ""
) -> list[dict]:
    """
    Submits the Quant's proposals to the Risk Guardian.
    btc_context: Data describing the current state of BTC if not in proposals.
    """
    if not GROQ_API_KEY or not proposals:
        return []

    client = AsyncGroq(api_key=GROQ_API_KEY)
    
    # Format the debate packet
    prompt_lines = []
    
    if recent_memory:
        prompt_lines.append(recent_memory)
        prompt_lines.append("If the Quant has been losing recently, you must be EXTREMELY STRICT on new proposals.")
        prompt_lines.append("\n==================================")
        
    prompt_lines.append("--- QUANT ANALYST PROPOSALS ---")
    for p in proposals:
        prompt_lines.append(
            f"TICKER: {p['ticker']} | ACTION: {p.get('proposed_action')} | "
            f"SIZE: {p.get('position_size_pct')}% | "
            f"REASON: {p.get('quant_reasoning')}"
        )
        
    prompt_lines.append("\n--- MACRO CONTEXT (BTC) ---")
    prompt_lines.append(btc_context)
    
    # Add raw structural data for context briefly
    prompt_lines.append("\n--- RAW DATA REFERENCE ---")
    for td in all_ticker_data:
        if td["ticker"] in [p["ticker"] for p in proposals] or td["ticker"] == "BTC":
            prompt_lines.append(f"\n{td['condensed']}")

    user_prompt = "\n".join(prompt_lines)

    try:
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": RISK_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.1,  # Lower temp for Risk Guardian
        )
        raw = response.choices[0].message.content.strip()
        parsed = _extract_json_risk(raw)
        
        # Merge risk verdicts back into proposals
        final_decisions = []
        for p in proposals:
            ticker = p["ticker"]
            # Find matching risk review
            review = next((r for r in parsed if r.get("ticker", "").upper() == ticker.upper()), None)
            
            p["verdict"] = "REJECTED"
            p["risk_reasoning"] = "No review from Guardian."
            
            if review:
                verdict = review.get("verdict", "REJECTED").upper()
                p["verdict"] = verdict if verdict in ("APPROVED", "REJECTED") else "REJECTED"
                
                new_size = review.get("final_position_size_pct", p["position_size_pct"])
                p["position_size_pct"] = min(p["position_size_pct"], max(1, int(new_size)))
                p["risk_reasoning"] = review.get("risk_reasoning", "No reason given.")
                
            final_decisions.append(p)
            logger.info("Risk Guardian [%s]: %s (Reason: %s)", ticker, p['verdict'], p['risk_reasoning'])
            
        return final_decisions

    except Exception as e:
        logger.error("Risk Guardian Error: %s", e)
        # Fail-OPEN: if Guardian crashes, APPROVE all proposals.
        # The engine-level confidence threshold is still a safety net.
        logger.warning("Risk Guardian offline — APPROVING all proposals (fail-open mode).")
        for p in proposals:
            p["verdict"] = "APPROVED"
            p["risk_reasoning"] = f"GUARDIAN OFFLINE — auto-approved (fail-open) — {e}"
        return proposals
