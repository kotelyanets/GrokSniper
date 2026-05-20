"""
conftest.py
-----------
Shared pytest fixtures and configuration for GrokSniper test suite.

Sets DRY_RUN=True and dummy env vars so tests never touch real APIs or DB.
"""

import os
import pytest
from dotenv import load_dotenv
load_dotenv()

# ── Set all env vars BEFORE any backend module is imported ──────────────────
os.environ.setdefault("DRY_RUN",             "True")
os.environ.setdefault("PAPER_TRADE",         "True")
os.environ.setdefault("DATABASE_URL",        os.getenv("DATABASE_URL", "postgresql+asyncpg://groksniper_user:change_me_strong_password@localhost:5432/groksniper"))
os.environ.setdefault("ANTHROPIC_API_KEY",   "test-key")
os.environ.setdefault("GROQ_API_KEY",        "test-key")
os.environ.setdefault("BINANCE_API_KEY",     "test-key")
os.environ.setdefault("BINANCE_API_SECRET",  "test-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN",  "")
os.environ.setdefault("TELEGRAM_CHAT_ID",    "")
os.environ.setdefault("INITIAL_EQUITY",      "1000.0")
os.environ.setdefault("WATCHLIST",           "BTC,ETH,SOL")
os.environ.setdefault("CLAUDE_MODEL",        "claude-sonnet-4-20250514")


# ── Shared mock fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def anthropic_response_factory():
    """Returns a factory that builds fake Anthropic API response objects."""
    from unittest.mock import MagicMock

    def _build(content: str):
        msg = MagicMock()
        msg.content = [MagicMock(text=content)]
        return msg

    return _build


@pytest.fixture()
def mock_exchange():
    """A pre-configured AsyncMock for CryptoExchange with sane defaults."""
    from unittest.mock import AsyncMock
    ex = AsyncMock()
    ex.get_balance = AsyncMock(return_value={"total_usdt": 1000.0, "holdings": []})
    ex.get_price   = AsyncMock(return_value=50000.0)
    ex.place_order = AsyncMock(return_value={"status": "success", "price": 50000.0, "amount": 0.001})
    return ex


@pytest.fixture()
def mock_db_session():
    """An async context-manager mock for AsyncSessionLocal / get_session."""
    from unittest.mock import AsyncMock, MagicMock
    session  = AsyncMock()
    result   = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar.return_value = 0
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.commit  = AsyncMock()
    session.add     = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__  = AsyncMock(return_value=False)
    return cm
