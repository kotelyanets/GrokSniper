"""
state.py
--------
Shared, module-level state for GrokSniper AI.

Holds:
  - bot_state dict (visible on the dashboard)
  - DashboardWSManager (live WebSocket push to dashboard clients)
  - WATCHLIST configuration
  - Convenience helpers: broadcast_to_dashboard(), update_bot_state()

Import from here whenever you need to read or write bot state or
push an event to the frontend WebSocket clients.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger("groksniper.api")

# ---------------------------------------------------------------------------
# Regime state cache (updated once per cycle, shared across tickers)
# ---------------------------------------------------------------------------
_current_regime    = "PURE_AI"
_regime_params: dict = {}
_regime_confidence = 100.0

# ---------------------------------------------------------------------------
# Bot state — shown on the dashboard status card
# ---------------------------------------------------------------------------
bot_state: dict = {
    "status":     "System Initialized",
    "last_action": "None",
    "started_at": datetime.utcnow().isoformat(),
}

# ---------------------------------------------------------------------------
# Watchlist — configurable via WATCHLIST env var
# ---------------------------------------------------------------------------
WATCHLIST: list[str] = [
    t.strip()
    for t in os.getenv("WATCHLIST", "BTC,ETH,SOL,DOGE,XRP").split(",")
    if t.strip()
]


# ---------------------------------------------------------------------------
# Dashboard WebSocket Manager
# ---------------------------------------------------------------------------
class DashboardWSManager:
    """Manages all active WebSocket connections from the dashboard frontend."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        logger.info(f"[WS Dashboard] Client connected. Total: {len(self._clients)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        logger.info(f"[WS Dashboard] Client disconnected. Total: {len(self._clients)}")

    async def broadcast(self, message: dict) -> None:
        """Fire-and-forget broadcast to all connected dashboard clients."""
        if not self._clients:
            return
        dead: set[WebSocket] = set()
        payload = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead


# Module-level singleton
dashboard_ws_manager = DashboardWSManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def broadcast_to_dashboard(event: str, data: dict) -> None:
    """Convenience wrapper — all broadcasts include a type field."""
    await dashboard_ws_manager.broadcast({"type": event, **data})


def update_bot_state(status: str | None = None, action: str | None = None) -> None:
    """Update bot_state and push it to all connected dashboard clients."""
    if status is not None:
        bot_state["status"] = status
    if action is not None:
        bot_state["last_action"] = action
    asyncio.ensure_future(broadcast_to_dashboard("bot_state", bot_state.copy()))
