"""
data_tools.py
-------------
MCP / Data-Bridge tool for the Board of Directors crew.
Reads the Phase 51/52 shadow log CSV and returns the latest market
statistics so AI agents can reason over real data.
"""

import os
import csv
import logging
from pathlib import Path

from crewai.tools import tool

logger = logging.getLogger(__name__)

# Resolve path: backend/src/agents/data_tools.py → backend/logs/shadow_statistics.csv
_CSV_PATH = Path(__file__).resolve().parents[2] / "logs" / "shadow_statistics.csv"


@tool("ReadShadowCSV")
def read_shadow_csv(limit: int = 5) -> str:
    """Use this tool to read the latest market statistics from the
    shadow_statistics.csv log file.

    The CSV contains one row per scan cycle with the following columns:
    Timestamp, Ticker, Price, Regime, MTF_Aligned, RSI, EMA_20, EMA_50,
    MACD_Cross, Volume_Ratio, ATR, Funding_Rate, OBI (Order Book Imbalance),
    Volume_Delta, AI_Sentiment, and Action_Signal.

    OBI (Order Book Imbalance) is positive when buy-side dominates, negative
    when sell-side dominates. Volume Delta shows net buying vs selling volume.
    Use these together with Funding_Rate and Regime to assess market intent.

    Args:
        limit: Number of most-recent rows to return (default 5).

    Returns:
        A human-readable string with the last *limit* rows of market data,
        or an error message if the file is unavailable.
    """
    csv_path = str(_CSV_PATH)

    if not os.path.exists(csv_path):
        return f"ERROR: Shadow statistics CSV not found at {csv_path}"

    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as fh:
            reader = list(csv.DictReader(fh))

        if not reader:
            return "ERROR: Shadow statistics CSV is empty."

        tail = reader[-limit:]

        lines = []
        for i, row in enumerate(tail, 1):
            lines.append(
                f"--- Row {i} ---\n"
                f"  Timestamp    : {row.get('Timestamp', 'N/A')}\n"
                f"  Ticker       : {row.get('Ticker', 'N/A')}\n"
                f"  Price        : {row.get('Price', 'N/A')}\n"
                f"  Regime       : {row.get('Regime', 'N/A')}\n"
                f"  MTF Aligned  : {row.get('MTF_Aligned', 'N/A')}\n"
                f"  RSI          : {row.get('RSI', 'N/A')}\n"
                f"  EMA 20       : {row.get('EMA_20', 'N/A')}\n"
                f"  EMA 50       : {row.get('EMA_50', 'N/A')}\n"
                f"  MACD Cross   : {row.get('MACD_Cross', 'N/A')}\n"
                f"  Volume Ratio : {row.get('Volume_Ratio', 'N/A')}\n"
                f"  ATR          : {row.get('ATR', 'N/A')}\n"
                f"  Funding Rate : {row.get('Funding_Rate', 'N/A')}\n"
                f"  OBI          : {row.get('OBI', 'N/A')}\n"
                f"  Volume Delta : {row.get('Volume_Delta', 'N/A')}\n"
                f"  AI Sentiment : {row.get('AI_Sentiment', 'N/A')}\n"
                f"  Action Signal: {row.get('Action_Signal', 'N/A')}"
            )

        header = f"📊 Shadow Statistics — Last {len(tail)} rows\n{'=' * 48}\n"
        return header + "\n".join(lines)

    except Exception as exc:
        logger.error(f"[ReadShadowCSV] Failed to read CSV: {exc}")
        return f"ERROR: Could not read shadow statistics — {exc}"
