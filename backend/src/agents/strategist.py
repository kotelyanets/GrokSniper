"""
strategist.py
-------------
CrewAI Quant Strategist Agent.
"""

import os

from crewai import Agent, Task
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from backend.src.agents.tools import fetch_deep_chart_data

load_dotenv()

# ---------------------------------------------------------------------------
# LLM — Anthropic Claude (low temp for analytical precision)
# ---------------------------------------------------------------------------
llm = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0.2,
)

# ---------------------------------------------------------------------------
# Agent: Quant Strategist
# ---------------------------------------------------------------------------
quant_strategist = Agent(
    role="Quant Strategist",
    goal=(
        "Determine Market Regime (Trend/Range/Chop) for {ticker} "
        "using DeepChartData and select optimal strategy."
    ),
    backstory=(
        "Quant strategist. Obsessed with price action and multi-timeframe "
        "structure. Classifies regimes: STRONG_UPTREND, STRONG_DOWNTREND, "
        "MODERATE_TREND, RANGE, VOLATILE_CHOP. Never trades against the "
        "dominant trend. Chart structure > all."
    ),
    tools=[fetch_deep_chart_data],
    llm=llm,
    verbose=True,
)

# ---------------------------------------------------------------------------
# Task: Fetch chart data → classify regime → recommend strategy
# ---------------------------------------------------------------------------
strategist_task = Task(
    description=(
        "Fetch multi-timeframe data for {ticker} using FetchDeepChartDataTool. "
        "The tool returns a JSON object with per-timeframe metrics (close, rsi, adx, "
        "atr_pct, ema50_dist, ema200_dist, macd, trend, dir) inside key 'tf'. "
        "Rules:\n"
        "- Use 4h adx + dir for regime classification.\n"
        "- Use 1h + 15m for entry bias confirmation.\n"
        "- If regime is VOLATILE_CHOP → bias=neutral, strategy=No Trade.\n"
        "- Identify key S/R from ema50 and ema200 values across timeframes.\n"
        "Output ONLY the JSON below, no explanation:"
    ),
    expected_output=(
        'A JSON string: '
        '{"regime":"<STRONG_UPTREND|STRONG_DOWNTREND|MODERATE_TREND|RANGE|VOLATILE_CHOP>",'
        '"strategy":"<Trend Following|Mean Reversion|Breakout|No Trade>",'
        '"bias":"<bullish|bearish|neutral>",'
        '"confidence":<int 0-100>,'
        '"key_levels":"<key S/R price levels as string>",'
        '"reasoning":"<2-sentence max justification>"}'
    ),
    agent=quant_strategist,
)
