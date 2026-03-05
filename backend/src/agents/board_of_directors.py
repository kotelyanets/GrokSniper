"""
board_of_directors.py
---------------------
Phase 54 — Hierarchical Multi-Agent Architecture (Anthropic / Claude 3.5 Sonnet).

A CrewAI *Board of Directors* crew that reads the shadow market data
and produces a consensus LONG / SHORT / HOLD recommendation.

Agents
------
1. **Quant Analyst** — reads the shadow CSV and detects real vs spoofed
   order-book activity.
2. **Risk Guardian** — evaluates the analyst's signal and decides whether
   it is safe to allocate capital.

Usage
-----
    .\\backend\\venv\\Scripts\\python -m backend.src.agents.board_of_directors

Requirements in .env
--------------------
    ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import asyncio
import logging
from pathlib import Path

from crewai import Agent, Task, Crew, Process, LLM
from dotenv import load_dotenv

from backend.src.agents.data_tools import read_shadow_csv

# ---------------------------------------------------------------------------
# Robust .env loading — works regardless of which directory the script is
# launched from (project root, backend/, or anywhere else).
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()               # .../backend/src/agents/board_of_directors.py
_PROJECT_ROOT = _HERE.parents[3]               # .../sniper_bot/
_BACKEND_DIR  = _HERE.parents[2]               # .../sniper_bot/backend/

load_dotenv(_PROJECT_ROOT / ".env")            # ← most likely location
load_dotenv(_BACKEND_DIR  / ".env")            # backend/.env fallback
load_dotenv()                                  # cwd fallback

# Ensure the key is visible to all downstream libraries
os.environ.setdefault("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strict API key guard — fail fast with a clear message
# ---------------------------------------------------------------------------
_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
if not _ANTHROPIC_KEY:
    logger.warning("ANTHROPIC_API_KEY not set — Board of Directors disabled.")
    claude_llm = None
else:
    # ---------------------------------------------------------------------------
    # LLM — CrewAI native wrapper → Anthropic / Claude
    # ---------------------------------------------------------------------------
    claude_llm = LLM(
        model="anthropic/claude-3-5-sonnet-latest", 
        api_key=_ANTHROPIC_KEY,
        temperature=0.1 # Low temperature for strict, mathematical logic
    )

# ═══════════════════════════════════════════════════════════════════════════
# Agent 1 — Quant Analyst
# ═══════════════════════════════════════════════════════════════════════════
quant_analyst = Agent(
    role="Senior Quant",
    goal="Analyze order book imbalance (OBI) and Volume Delta to detect market spoofing or real trends.",
    backstory=(
        "You are an elite Wall Street quant who reads tape and L2 order books. "
        "You spot traps and spoofing that others miss. You cross-reference "
        "funding rates, RSI, and EMA structure to build a conviction score "
        "before recommending any trade direction."
    ),
    tools=[read_shadow_csv],
    llm=claude_llm,
    verbose=True,
    allow_delegation=False,
)

# ═══════════════════════════════════════════════════════════════════════════
# Agent 2 — Risk Guardian
# ═══════════════════════════════════════════════════════════════════════════
risk_guardian = Agent(
    role="Chief Risk Officer",
    goal="Evaluate the analyst signal and decide if it is safe to allocate capital.",
    backstory=(
        "You are a paranoid risk manager. You hate losing money. "
        "You veto trades that show a bad risk-reward ratio, extreme funding, "
        "or a choppy/unconfirmed regime. When in doubt, HOLD."
    ),
    llm=claude_llm,
    verbose=True,
    allow_delegation=False,
)

# ═══════════════════════════════════════════════════════════════════════════
# Tasks
# ═══════════════════════════════════════════════════════════════════════════
analysis_task = Task(
    description=(
        "Use your tool to read the last 5 rows of market data from the shadow "
        "statistics CSV.\n\n"
        "For each ticker:\n"
        "1. Examine OBI — positive = buy pressure, negative = sell pressure.\n"
        "2. Cross-reference Volume Delta to confirm whether the OBI is backed "
        "   by real volume (confirmation) or is likely spoofing.\n"
        "3. Check RSI, Funding Rate, and Regime for extra confluence.\n\n"
        "End with a clear recommendation: LONG, SHORT, or HOLD per ticker, "
        "a confidence percentage (0-100%), and one sentence of reasoning."
    ),
    expected_output=(
        "A structured report: LONG / SHORT / HOLD per ticker with "
        "confidence % and a brief rationale for each."
    ),
    agent=quant_analyst,
)

risk_review_task = Task(
    description=(
        "Review the Quant Analyst's recommendations.\n\n"
        "For each ticker:\n"
        "1. Check whether the market Regime supports the trade direction.\n"
        "2. Flag extreme funding rates that could trigger a squeeze.\n"
        "3. Confirm volume ratio is sufficient to justify entry.\n\n"
        "APPROVE or VETO each trade with a one-line justification. "
        "If vetoed, change the signal to HOLD."
    ),
    expected_output=(
        "Final board decision per ticker: "
        "APPROVED LONG / APPROVED SHORT / VETOED → HOLD, with risk justification."
    ),
    agent=risk_guardian,
)

# ═══════════════════════════════════════════════════════════════════════════
# Crew — Sequential: Analyst → Risk Guardian
# ═══════════════════════════════════════════════════════════════════════════
board_crew = Crew(
    agents=[quant_analyst, risk_guardian],
    tasks=[analysis_task, risk_review_task],
    process=Process.sequential,
    verbose=True,
)

async def get_board_decision() -> str:
    """
    Executes the board crew kickoff in a separate thread to avoid blocking the event loop.
    Returns the final board decision string.
    """
    if not claude_llm:
        return "🚨 Board error: ANTHROPIC_API_KEY missing. Board of Directors is disabled."
    try:
        result = await asyncio.to_thread(board_crew.kickoff)
        return str(result)
    except Exception as e:
        logger.error(f"Board decision error: {e}")
        return f"🚨 Board error: {str(e)}"

# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n🏛️  Board of Directors — Initiating Session …\n")
    
    result = asyncio.run(get_board_decision())
    
    print("\n" + "=" * 60)
    print("📋  FINAL BOARD DECISION")
    print("=" * 60)
    print(result)
