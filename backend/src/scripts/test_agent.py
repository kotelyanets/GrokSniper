"""
test_agent.py
-------------
Quick smoke-test for the CrewAI Fundamental Analyst Agent.

Usage (from project root):
    python -m backend.src.scripts.test_agent

Requires:
    - ANTHROPIC_API_KEY set in .env
    - PostgreSQL running with news_logs data
"""

import json
import sys

from crewai import Crew
from dotenv import load_dotenv

load_dotenv()

from backend.src.agents.fundamental import (
    analyze_fundamental_task,
    fundamental_analyst,
)


def main() -> None:
    ticker = "BTC"
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()

    print(f"\n{'='*60}")
    print(f"  CrewAI Fundamental Analyst — Analyzing {ticker}")
    print(f"{'='*60}\n")

    crew = Crew(
        agents=[fundamental_analyst],
        tasks=[analyze_fundamental_task],
        verbose=True,
    )

    result = crew.kickoff(inputs={"ticker": ticker})

    print(f"\n{'='*60}")
    print("  RAW RESULT")
    print(f"{'='*60}")
    print(result)

    # Try to parse as JSON for a cleaner display
    try:
        parsed = json.loads(str(result))
        print(f"\n{'='*60}")
        print("  PARSED OUTPUT")
        print(f"{'='*60}")
        print(f"  Score     : {parsed.get('score', 'N/A')}")
        print(f"  Reasoning : {parsed.get('reasoning', 'N/A')}")
    except (json.JSONDecodeError, TypeError):
        print("\n  (Could not parse result as JSON — see raw output above)")

    print()


if __name__ == "__main__":
    main()
