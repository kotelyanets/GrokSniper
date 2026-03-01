"""
fundamental.py
--------------
CrewAI Risk & Catalyst Filter Agent.
Secondary filter (20% weight) — chart analysis takes priority.
"""

import os

from crewai import Agent, Task
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from backend.src.agents.tools import fetch_latest_news

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
# Agent: Risk & Catalyst Filter
# ---------------------------------------------------------------------------
fundamental_analyst = Agent(
    role="Risk & Catalyst Filter",
    goal=(
        "Scan recent news for {ticker}. Flag only high-impact risks "
        "or major catalysts. You are a secondary filter (20% weight)."
    ),
    backstory=(
        "Risk analyst. 80% of news is noise. Only flag: exchange hacks, "
        "regulatory bans, protocol exploits, ETF approvals, mainnet launches. "
        "Score routine news near 0. Do not make trade decisions."
    ),
    tools=[fetch_latest_news],
    llm=llm,
    verbose=True,
)

# ---------------------------------------------------------------------------
# Task: Filter news for risks/catalysts
# ---------------------------------------------------------------------------
analyze_fundamental_task = Task(
    description=(
        "Fetch news for {ticker} using FetchLatestNewsTool. "
        "The tool returns a minified JSON array: [{\"date\":\"...\",\"text\":\"...\"}]. "
        "Rules:\n"
        "- Score: -100 (catastrophic risk) to +100 (major catalyst).\n"
        "- High-impact risks: hacks, bans, lawsuits, exploits, major delistings → score < -50.\n"
        "- Major catalysts: ETF approval, mainnet launch, institutional buy → score > 50.\n"
        "- Routine news, opinions, minor updates → score near 0.\n"
        "Output ONLY the JSON below, no explanation:"
    ),
    expected_output=(
        'A JSON string: '
        '{"score":<int -100 to 100>,'
        '"confidence":<int 0-100>,'
        '"reasoning":"<2-sentence max, risk/catalyst focus only>"}'
    ),
    agent=fundamental_analyst,
)
