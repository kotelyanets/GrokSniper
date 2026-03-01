"""
lead_cio.py
-----------
CrewAI Lead CIO Agent.
Synthesizes Quant Strategist (80% weight) + Risk Filter (20% weight)
into a final trade decision.
"""

import os

from crewai import Agent, Task
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

# ---------------------------------------------------------------------------
# LLM — Anthropic Claude
# ---------------------------------------------------------------------------
llm = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0.3,
)

# ---------------------------------------------------------------------------
# Agent: Chief Investment Officer
# ---------------------------------------------------------------------------
lead_cio = Agent(
    role="Chief Investment Officer",
    goal=(
        "Final trade decision for {ticker}: 80% weight to Quant Strategist TA, "
        "20% to Risk/Catalyst Filter news."
    ),
    backstory=(
        "Disciplined CIO. Chart dictates direction — news is a risk override only. "
        "Rules: if chart says SHORT but news is mildly positive → trust the chart. "
        "Only catastrophic fundamentals (hack, ban) override a clear technical setup. "
        "Output raw conviction score: -100 (extreme bearish) to +100 (extreme bullish)."
    ),
    tools=[],  # No tools — pure synthesis from context
    llm=llm,
    verbose=True,
)

# ---------------------------------------------------------------------------
# Task: Synthesize Strategist + Fundamental → final decision
# NOTE: context= is set at Crew-assembly time in crew_analyzer.py
# ---------------------------------------------------------------------------
cio_task = Task(
    description=(
        "You have two inputs:\n"
        "1. Quant Strategist (80%): regime, strategy, bias, confidence, key_levels, reasoning.\n"
        "2. Risk/Catalyst Filter (20%): score, confidence, reasoning.\n\n"
        "Rules:\n"
        "- Primary: use Strategist bias + confidence as base for your score.\n"
        "- Adjust mildly (max ±15 pts) based on the news filter score.\n"
        "- Only override chart if news score < -75 (catastrophic event).\n"
        "- If regime=VOLATILE_CHOP OR strategy=No Trade → output score near 0.\n"
        "Output ONLY the JSON below, no explanation:"
    ),
    expected_output=(
        'A JSON string: '
        '{"score":<int -100 to 100>,'
        '"confidence":<int 0-100>,'
        '"reasoning":"<2-sentence max justification>"}'
    ),
    agent=lead_cio,
)
