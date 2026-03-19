"""
test_api.py
-----------
Smoke / integration tests for the FastAPI REST API.

Uses FastAPI's built-in TestClient (synchronous httpx wrapper).
The DB is mocked at the session level so no real PostgreSQL is needed.
Run with:  pytest backend/tests/test_api.py -v
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Client fixture — patches DB session so no real Postgres is needed
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    """
    Creates a TestClient for the FastAPI app.
    
    Patches:
      - AsyncSessionLocal  →  returns an async context manager with mocked session
      - CryptoExchange     →  returns a mock with sim balance data
    """
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)

    mock_exchange = AsyncMock()
    mock_exchange.get_balance = AsyncMock(return_value={
        "total_usdt": 1250.0,
        "holdings": [],
    })

    with (
        patch("backend.src.api.routes._exchange", mock_exchange),
        patch("backend.src.db.database.AsyncSessionLocal", return_value=mock_session),
    ):
        # Import app AFTER patches are applied
        from backend.src.api.server import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
class TestHealthEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_response_has_status_field(self, client):
        data = client.get("/api/health").json()
        assert "status" in data

    def test_response_has_mode_field(self, client):
        data = client.get("/api/health").json()
        assert data["mode"] == "FULL_AUTOMATION"

    def test_response_has_database_field(self, client):
        data = client.get("/api/health").json()
        assert "database" in data


# ---------------------------------------------------------------------------
# /api/bot-status
# ---------------------------------------------------------------------------
class TestBotStatusEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/bot-status")
        assert response.status_code == 200

    def test_has_status_field(self, client):
        data = client.get("/api/bot-status").json()
        assert "status" in data

    def test_has_started_at(self, client):
        data = client.get("/api/bot-status").json()
        assert "started_at" in data

    def test_includes_trading_mode_flags(self, client):
        data = client.get("/api/bot-status").json()
        assert "trading_mode" in data
        assert "paper_trade" in data["trading_mode"]
        assert "dry_run" in data["trading_mode"]
        assert "binance_testnet" in data["trading_mode"]
        assert "live_trading_enabled" in data["trading_mode"]

    def test_live_trading_enabled_false_when_any_safety_flag_enabled(self, client):
        with patch.dict(
            os.environ,
            {"PAPER_TRADE": "True", "DRY_RUN": "False", "BINANCE_TESTNET": "False"},
            clear=False,
        ):
            data = client.get("/api/bot-status").json()
            assert data["trading_mode"]["live_trading_enabled"] is False

    def test_live_trading_enabled_true_only_when_all_live_flags_set(self, client):
        with patch.dict(
            os.environ,
            {"PAPER_TRADE": "False", "DRY_RUN": "False", "BINANCE_TESTNET": "False"},
            clear=False,
        ):
            data = client.get("/api/bot-status").json()
            assert data["trading_mode"]["live_trading_enabled"] is True


# ---------------------------------------------------------------------------
# /api/news
# ---------------------------------------------------------------------------
class TestNewsEndpoint:
    def test_returns_200_or_empty_list(self, client):
        response = client.get("/api/news")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# /api/trades
# ---------------------------------------------------------------------------
class TestTradesEndpoint:
    def test_returns_200_or_empty_list(self, client):
        response = client.get("/api/trades")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# /api/analytics
# ---------------------------------------------------------------------------
class TestAnalyticsEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/analytics")
        assert response.status_code == 200

    def test_empty_result_structure(self, client):
        data = client.get("/api/analytics").json()
        # Either a valid analytics object or an error dict
        assert isinstance(data, dict)
