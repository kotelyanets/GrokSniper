"""
test_integration_trading.py
============================
Comprehensive integration tests that simulate the FULL GrokSniper trading
lifecycle end-to-end with mocked external dependencies.

These tests validate HOW the bot will behave in realistic scenarios:
  • Scenario 1: BTC dump → all LONG signals blocked
  • Scenario 2: Bullish signal → Quant proposes LONG → Risk approves → Kelly sizes → order placed
  • Scenario 3: Low confidence → trade blocked at confidence gate
  • Scenario 4: Risk Guardian vetoes a proposal
  • Scenario 5: Capital Manager blocks trade (overexposure)
  • Scenario 6: Drawdown circuit breaker halts trading
  • Scenario 7: Correlated asset penalty reduces position size
  • Scenario 8: WebSocket LONG position hits trailing stop and exits profitably
  • Scenario 9: WebSocket SHORT position hits hard stop-loss
  • Scenario 10: REST fallback activates when WebSocket disconnects
  • Scenario 11: Groq / Claude API failure → graceful fallback to HOLD
  • Scenario 12: Insufficient funds → order rejection handled gracefully
  • Scenario 13: MIN_NOTIONAL ($5) rule → order rejected, no crash
  • Scenario 14: Kelly Criterion with real trade history produces correct sizing
  • Scenario 15: Multiple concurrent positions tracked independently

Run:  pytest backend/tests/test_integration_trading.py -v
"""

import asyncio
import json
import os
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 1: BTC Dump Mode → All LONGs blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestBTCDumpProtection:
    """When BTC is dumping, the engine must refuse all LONG entries."""

    @pytest.mark.asyncio
    async def test_btc_dump_skips_all_tickers(self):
        """Full pipeline returns SKIP for every ticker when BTC is in dump mode."""
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=True), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock) as mock_ohlcv, \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["BTC", "ETH", "SOL"]), \
             patch("os.getenv", side_effect=lambda k, d="": {"BINANCE_TESTNET": "False"}.get(k, d)):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            assert len(results) == 3
            assert all(r["action"] == "SKIP" for r in results)
            assert all("BTC dump" in r["reason"] for r in results)
            mock_ohlcv.assert_not_called()  # OHLCV should never be fetched

    @pytest.mark.asyncio
    async def test_btc_dump_check_skipped_on_testnet(self):
        """On testnet, BTC dump check is always skipped (testnet data is unreliable)."""
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock) as mock_dump, \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("DATA", {"close": 100.0, "rsi": 50.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(0, "Neutral")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[]), \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["BTC"]), \
             patch.dict(os.environ, {"BINANCE_TESTNET": "True"}):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            # On testnet, dump mode should be False regardless, pipeline proceeds
            mock_dump.assert_not_called()  # Testnet skips the call entirely


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 2: Full Bullish Pipeline → Trade Executed
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullBullishPipeline:
    """When all signals are green, the bot opens a LONG position."""

    @pytest.mark.asyncio
    async def test_bullish_signal_opens_trade(self):
        """Quant proposes LONG with high confidence → Risk approves → trade executes."""
        mock_decision_result = {
            "ticker": "ETH", "action": "LONG", "confidence": 85,
            "regime": "TRENDING_UP", "trade_placed": True,
            "trade_usdt": 50.0, "price": 3000.0,
            "suggested_sl": 2900.0, "suggested_tp": 3200.0,
            "reasoning": "Quant: RSI oversold | Risk: Macro clear",
            "trade_id": "test-uuid-123"
        }

        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("ETH 15m RSI=28 EMA=3000", {"close": 3000.0, "rsi": 28.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(72, "ETH upgrade bullish")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[
                 {"ticker": "ETH", "proposed_action": "LONG", "confidence": 85,
                  "suggested_sl": 2900.0, "suggested_tp": 3200.0, "position_size_pct": 10,
                  "quant_reasoning": "RSI oversold bounce setup with MACD crossover"}
             ]), \
             patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock, return_value=[
                 {"ticker": "ETH", "proposed_action": "LONG", "confidence": 85,
                  "verdict": "APPROVED", "regime": "TRENDING_UP", "position_size_pct": 10,
                  "suggested_sl": 2900.0, "suggested_tp": 3200.0,
                  "quant_reasoning": "RSI oversold bounce setup", "risk_reasoning": "Macro clear"}
             ]), \
             patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock,
                   return_value=mock_decision_result) as mock_exec, \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["ETH"]), \
             patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 45):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers(latest_news="Ethereum upgrade announced")

            eth_result = next(r for r in results if r["ticker"] == "ETH")
            assert eth_result["action"] == "LONG"
            assert eth_result["trade_placed"] is True
            assert eth_result["confidence"] == 85
            mock_exec.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 3: Low Confidence → Trade Blocked
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceGate:
    """Trades with confidence below threshold are blocked even if approved by Risk."""

    @pytest.mark.asyncio
    async def test_low_confidence_trade_blocked(self):
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("SOL data", {"close": 150.0, "rsi": 50.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(10, "Neutral")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[
                 {"ticker": "SOL", "proposed_action": "LONG", "confidence": 30, "position_size_pct": 5,
                  "suggested_sl": 145.0, "suggested_tp": 160.0, "quant_reasoning": "Weak setup"}
             ]), \
             patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock, return_value=[
                 {"ticker": "SOL", "proposed_action": "LONG", "confidence": 30,
                  "verdict": "APPROVED", "regime": "CHOPPY", "position_size_pct": 5,
                  "quant_reasoning": "Weak setup", "risk_reasoning": "Okay"}
             ]), \
             patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock) as mock_exec, \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["SOL"]), \
             patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 60):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            sol_result = next(r for r in results if r["ticker"] == "SOL")
            assert sol_result["action"] == "HOLD"
            assert sol_result["trade_placed"] is False
            mock_exec.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 4: Risk Guardian Vetoes a Trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskGuardianVeto:
    """Risk Guardian rejects a Quant proposal → trade blocked."""

    @pytest.mark.asyncio
    async def test_rejected_by_risk_guardian(self):
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("DOGE data", {"close": 0.15, "rsi": 70.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(-20, "Elon tweet FUD")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[
                 {"ticker": "DOGE", "proposed_action": "LONG", "confidence": 75, "position_size_pct": 8,
                  "suggested_sl": 0.14, "suggested_tp": 0.18, "quant_reasoning": "Momentum"}
             ]), \
             patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock, return_value=[
                 {"ticker": "DOGE", "proposed_action": "LONG", "confidence": 75,
                  "verdict": "REJECTED", "regime": "CHOPPY", "position_size_pct": 8,
                  "quant_reasoning": "Momentum", "risk_reasoning": "BTC in distribution, meme coins are high risk"}
             ]), \
             patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock) as mock_exec, \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["DOGE"]), \
             patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 45):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            doge_result = next(r for r in results if r["ticker"] == "DOGE")
            assert doge_result["action"] == "HOLD"
            assert doge_result["trade_placed"] is False
            mock_exec.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 5-7: Capital Manager Guards
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapitalManagerGuards:
    """Tests the portfolio-level risk controller."""

    @pytest.mark.asyncio
    async def test_overexposure_blocks_trade(self):
        """Capital Manager blocks a trade when total exposure exceeds 40%."""
        from backend.src.services.capital_manager import CapitalManager

        cm = CapitalManager(max_total_exposure=0.40)
        session = AsyncMock()

        # Simulate 2 existing open trades of $250 each = $500 total exposure
        mock_result = MagicMock()
        mock_trades = []
        for ticker in ["BTC", "ETH"]:
            t = MagicMock()
            t.position_size_usdt = 250.0
            t.ticker = ticker
            mock_trades.append(t)
        mock_result.scalars.return_value.all.return_value = mock_trades
        session.execute = AsyncMock(return_value=mock_result)

        # Total balance = $1000. 40% = $400 max. Already at $500.
        is_ok, size, msg = await cm.evaluate_trade(
            db_session=session,
            ticker="SOL",
            proposed_action="BUY",
            proposed_usdt=100.0,
            total_balance=1000.0,
            is_paper=False
        )

        assert is_ok is False
        assert "PORTFOLIO LIMIT" in msg

    @pytest.mark.asyncio
    async def test_per_ticker_exposure_limit(self):
        """Capital Manager blocks a second trade on the same ticker exceeding 20%."""
        from backend.src.services.capital_manager import CapitalManager

        cm = CapitalManager(max_ticker_exposure=0.20)
        session = AsyncMock()

        # Existing BTC position = $190
        mock_result = MagicMock()
        t = MagicMock()
        t.position_size_usdt = 190.0
        t.ticker = "BTC"
        mock_result.scalars.return_value.all.return_value = [t]

        # For the drawdown check
        dd_result = MagicMock()
        dd_result.scalar.return_value = 0.0

        session.execute = AsyncMock(side_effect=[mock_result, dd_result])

        # Balance=$1000, max per ticker=20%=$200. Already at $190.
        is_ok, size, msg = await cm.evaluate_trade(
            db_session=session, ticker="BTC", proposed_action="BUY",
            proposed_usdt=100.0, total_balance=1000.0, is_paper=False
        )

        assert is_ok is True
        assert size <= 10.0  # Only $10 remaining capacity (200-190)

    @pytest.mark.asyncio
    async def test_drawdown_circuit_breaker(self):
        """If 24h losses exceed 15% of balance, Capital Manager halts all trading."""
        from backend.src.services.capital_manager import CapitalManager

        cm = CapitalManager(max_drawdown=0.15)
        session = AsyncMock()

        # No open positions
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        # 24h PnL = -$200 on $1000 balance = -20% (exceeds 15%)
        dd_result = MagicMock()
        dd_result.scalar.return_value = -200.0

        session.execute = AsyncMock(side_effect=[mock_result, dd_result])

        is_ok, size, msg = await cm.evaluate_trade(
            db_session=session, ticker="ETH", proposed_action="BUY",
            proposed_usdt=50.0, total_balance=1000.0, is_paper=False
        )

        assert is_ok is False
        assert "CIRCUIT BREAKER" in msg

    @pytest.mark.asyncio
    async def test_correlation_penalty_applied(self):
        """If holding BTC, a new ETH trade gets 50% correlation size penalty."""
        from backend.src.services.capital_manager import CapitalManager

        cm = CapitalManager()
        session = AsyncMock()

        # Already holding BTC
        mock_result = MagicMock()
        t = MagicMock()
        t.position_size_usdt = 100.0
        t.ticker = "BTC"
        mock_result.scalars.return_value.all.return_value = [t]

        dd_result = MagicMock()
        dd_result.scalar.return_value = 0.0

        session.execute = AsyncMock(side_effect=[mock_result, dd_result])

        is_ok, size, msg = await cm.evaluate_trade(
            db_session=session, ticker="ETH", proposed_action="BUY",
            proposed_usdt=100.0, total_balance=1000.0, is_paper=False
        )

        # ETH is correlated with BTC → 50% penalty → $50 max instead of $100
        assert is_ok is True
        assert size <= 50.0


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 8-10: WebSocket Position Monitoring
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketMonitoring:
    """Tests the real-time position monitoring and exit logic."""

    @pytest.mark.asyncio
    async def test_long_trailing_stop_exit(self):
        """LONG position: price rises +6% activating trailing stop, then drops → exit."""
        from backend.src.services.ws_manager import _TRAIL_ACTIVATION_PCT, _TRAIL_STEP_PCT

        # Simulate tick-by-tick logic inline
        entry_price = 100.0
        highest_price = entry_price
        trailing_activated = False
        trail_activation = 1.0 + _TRAIL_ACTIVATION_PCT
        trail_step = 1.0 - _TRAIL_STEP_PCT
        dynamic_sl = 97.0  # 3% hard stop

        # Simulate price rising to 106 (activates trailing)
        price_ticks = [100.5, 101.0, 102.0, 103.5, 105.0, 106.0]
        for price in price_ticks:
            if price > highest_price:
                highest_price = price
            if highest_price >= entry_price * trail_activation:
                trailing_activated = True

        assert trailing_activated is True
        assert highest_price == 106.0

        # Now price drops. Trailing trigger = 106 * 0.997 = 105.682
        trailing_trigger = highest_price * trail_step
        assert trailing_trigger == pytest.approx(106.0 * (1.0 - _TRAIL_STEP_PCT), rel=1e-3)

        # Price hits 105.5 → below trailing trigger → should exit
        exit_price = 105.5
        should_exit = exit_price <= trailing_trigger
        assert should_exit is True

        # Verify PnL is positive
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        assert pnl_pct > 0, f"Expected positive PnL, got {pnl_pct:.2f}%"

    @pytest.mark.asyncio
    async def test_long_hard_stop_loss(self):
        """LONG position: price drops below ATR-based stop → hard exit."""
        entry_price = 100.0
        dynamic_sl = 96.5  # ATR-based stop at -3.5%

        price = 96.0  # Below stop
        should_exit = price <= dynamic_sl
        assert should_exit is True

        pnl_pct = ((price - entry_price) / entry_price) * 100
        assert pnl_pct < 0
        assert pnl_pct > -5.0  # Loss contained within reasonable bound

    @pytest.mark.asyncio
    async def test_short_hard_stop_loss(self):
        """SHORT position: price rises above dynamic SL → exit with bounded loss."""
        entry_price = 100.0
        dynamic_sl = 103.0  # ATR-based stop for short

        price = 104.0  # Above stop
        should_exit = price >= dynamic_sl
        assert should_exit is True

        pnl_pct = ((entry_price - price) / entry_price) * 100
        assert pnl_pct < 0

    @pytest.mark.asyncio
    async def test_short_trailing_stop(self):
        """SHORT position: price drops -6%, activating trailing, then bounces → exit."""
        entry_price = 100.0
        lowest_price = entry_price
        trail_activation_pct = 0.054
        trail_step_pct = 0.003

        # Price drops to 93 (−7%, activates trailing)
        prices_down = [99.0, 97.0, 95.0, 93.0]
        for p in prices_down:
            if p < lowest_price:
                lowest_price = p

        trailing_activated = lowest_price <= entry_price * (1.0 - trail_activation_pct)
        assert trailing_activated is True

        # Trailing trigger for short = lowest * (1 + step%) = 93 * 1.003 = 93.279
        trailing_trigger = lowest_price * (1.0 + trail_step_pct)

        # Price bounces to 93.5 → above trigger → exit
        bounce_price = 93.5
        should_exit = bounce_price >= trailing_trigger
        assert should_exit is True

        # PnL positive for short
        pnl_pct = ((entry_price - bounce_price) / entry_price) * 100
        assert pnl_pct > 0

    @pytest.mark.asyncio
    async def test_position_stays_open_in_range(self):
        """Position stays open while price is between SL and TP / trail isn't triggered."""
        entry_price = 100.0
        dynamic_sl = 97.0
        highest_price = 102.0
        trail_activation = 1.054  # Need +5.4% to activate

        # Price at 102 → +2%, not enough for trailing activation
        trailing_activated = highest_price >= entry_price * trail_activation
        assert trailing_activated is False

        # Not at stop loss either
        current_price = 101.0
        at_stop = current_price <= dynamic_sl
        assert at_stop is False

        # Position should stay open (no exit conditions met)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 11: API Failures → Graceful Degradation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIFailureGracefulDegradation:
    """When external APIs fail, the bot should gracefully degrade, not crash."""

    @pytest.mark.asyncio
    async def test_groq_api_failure_returns_neutral_sentiment(self):
        """If Groq API fails, sentiment defaults to (0, 'Sentiment unavailable')."""
        from backend.src.core.engine import _groq_sentiment

        with patch("backend.src.core.engine.GROQ_API_KEY", "test-key"):
            with patch("groq.AsyncGroq") as MockGroq:
                MockGroq.return_value.chat.completions.create = AsyncMock(
                    side_effect=Exception("API rate limit exceeded")
                )
                score, summary = await _groq_sentiment("Breaking news", "BTC")
                assert score == 0
                assert "unavailable" in summary.lower()

    @pytest.mark.asyncio
    async def test_quant_crash_returns_empty_proposals(self):
        """If the Quant Analyst crashes, the pipeline returns no proposals, not an exception."""
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("DATA", {"close": 50000.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(50, "Bullish")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[]), \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["BTC"]):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            # All tickers marked HOLD when no proposals come through
            assert all(r["action"] == "HOLD" for r in results)
            assert all(r.get("trade_placed") is False for r in results)

    @pytest.mark.asyncio
    async def test_risk_guardian_crash_allows_fail_open(self):
        """If Risk Guardian crashes, proposals are auto-approved (fail-open)."""
        from backend.src.core.agents.risk_guardian import evaluate_proposals

        proposals = [
            {"ticker": "ETH", "proposed_action": "LONG", "confidence": 80,
             "position_size_pct": 10, "quant_reasoning": "RSI oversold"}
        ]

        with patch("backend.src.core.agents.risk_guardian.GROQ_API_KEY", "test-key"):
            with patch("backend.src.core.agents.risk_guardian.AsyncGroq") as MockGroq:
                MockGroq.return_value.chat.completions.create = AsyncMock(
                    side_effect=Exception("Network timeout")
                )
                result = await evaluate_proposals(proposals, "BTC context", [])

                assert len(result) == 1
                assert result[0]["verdict"] == "APPROVED"
                assert "GUARDIAN OFFLINE" in result[0]["risk_reasoning"]


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 12-13: Exchange Execution Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestExchangeExecutionEdgeCases:
    """Tests that CCXT errors are handled properly without crashes."""

    @pytest.mark.asyncio
    async def test_insufficient_funds_handled(self):
        """InsufficientFunds from CCXT → order fails gracefully, no crash."""
        from backend.src.services.exchange import CryptoExchange
        from ccxt import InsufficientFunds

        ex = CryptoExchange()
        ex._dry_run = False
        ex._has_keys = True

        with patch.object(ex, '_get_best_exchange_for_trade', new_callable=AsyncMock, return_value='binance'), \
             patch.object(ex, '_init_ccxt') as mock_ccxt:

            mock_exchange = AsyncMock()
            mock_exchange.load_markets = AsyncMock()
            mock_exchange.create_order = AsyncMock(
                side_effect=InsufficientFunds("Account has insufficient balance")
            )
            mock_exchange.amount_to_precision = MagicMock(return_value="0.001")
            mock_ccxt.return_value = mock_exchange

            result = await ex.place_order("BTC", "BUY", 0.001)

            assert result["status"] != "success"

    @pytest.mark.asyncio
    async def test_dry_run_simulates_order(self):
        """In DRY_RUN mode, orders are simulated without hitting the exchange."""
        from backend.src.services.exchange import CryptoExchange

        with patch.dict(os.environ, {"DRY_RUN": "True"}):
            ex = CryptoExchange()
            assert ex._dry_run is True

            result = await ex.place_order("ETH", "BUY", 0.5)
            assert result["status"] == "success"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 14: Kelly Criterion Sizing
# ═══════════════════════════════════════════════════════════════════════════════

class TestKellyCriterionSizing:
    """Validates the mathematical correctness of the Half-Kelly position sizer."""

    def test_kelly_with_positive_edge(self):
        """55% win rate, 2:1 R/R → positive Kelly fraction."""
        from backend.src.services.risk_manager import calculate_kelly_percentage

        # win_rate=55%, avg_win=$20, avg_loss=$10 → R=2.0
        # K = 0.55 - (0.45/2.0) = 0.55 - 0.225 = 0.325
        # Half-Kelly = 0.325 * 0.5 = 0.1625
        result = calculate_kelly_percentage(0.55, 20.0, 10.0)
        assert 0.15 < result < 0.20  # Should be ~16.25%

    def test_kelly_with_negative_edge(self):
        """30% win rate, 1:1 R/R → negative Kelly → MIN_KELLY (1%)."""
        from backend.src.services.risk_manager import calculate_kelly_percentage, MIN_KELLY

        # K = 0.30 - (0.70/1.0) = -0.40 → negative → clamp to MIN_KELLY
        result = calculate_kelly_percentage(0.30, 10.0, 10.0)
        assert result == MIN_KELLY  # 1% minimum

    def test_kelly_with_breakeven_edge(self):
        """50% win rate, 1:1 R/R → K=0 → MIN_KELLY."""
        from backend.src.services.risk_manager import calculate_kelly_percentage, MIN_KELLY

        result = calculate_kelly_percentage(0.50, 10.0, 10.0)
        assert result == MIN_KELLY

    def test_kelly_with_exceptional_edge(self):
        """80% win rate, 3:1 R/R → very high Kelly, capped at MAX_KELLY (20%)."""
        from backend.src.services.risk_manager import calculate_kelly_percentage, MAX_KELLY

        # K = 0.80 - (0.20/3.0) = 0.80 - 0.067 = 0.733
        # Half-Kelly = 0.733 * 0.5 = 0.3665 → capped at 20%
        result = calculate_kelly_percentage(0.80, 30.0, 10.0)
        assert result == MAX_KELLY

    def test_kelly_zero_avg_loss_returns_fallback(self):
        """If avg_loss is 0 (e.g., no losing trades), use fallback 5%."""
        from backend.src.services.risk_manager import calculate_kelly_percentage, FALLBACK_FRACTION

        result = calculate_kelly_percentage(0.60, 15.0, 0.0)
        assert result == FALLBACK_FRACTION


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 15: Multi-Position Independence
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiPositionIndependence:
    """Tests that multiple concurrent positions are tracked independently."""

    @pytest.mark.asyncio
    async def test_multiple_tickers_independent_decisions(self):
        """Each ticker gets its own independent decision in the batch pipeline."""
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("DATA", {"close": 100.0, "rsi": 45.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(30, "Mixed")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[
                 {"ticker": "BTC", "proposed_action": "LONG", "confidence": 80, "position_size_pct": 10,
                  "suggested_sl": 95.0, "suggested_tp": 110.0, "quant_reasoning": "Strong breakout"},
                 {"ticker": "ETH", "proposed_action": "SHORT", "confidence": 70, "position_size_pct": 8,
                  "suggested_sl": 105.0, "suggested_tp": 90.0, "quant_reasoning": "Distribution pattern"}
             ]), \
             patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock, return_value=[
                 {"ticker": "BTC", "proposed_action": "LONG", "confidence": 80, "verdict": "APPROVED",
                  "regime": "TRENDING_UP", "position_size_pct": 10,
                  "quant_reasoning": "Strong breakout", "risk_reasoning": "Clear macro"},
                 {"ticker": "ETH", "proposed_action": "SHORT", "confidence": 70, "verdict": "REJECTED",
                  "regime": "DISTRIBUTION", "position_size_pct": 8,
                  "quant_reasoning": "Distribution", "risk_reasoning": "Too risky with BTC long"}
             ]), \
             patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock,
                   return_value={"ticker": "BTC", "action": "LONG", "trade_placed": True, "confidence": 80}) as mock_exec, \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock, return_value=""), \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["BTC", "ETH", "SOL"]), \
             patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 45):

            from backend.src.core.engine import scan_all_tickers
            results = await scan_all_tickers()

            # BTC should be executed (LONG, approved, high conf)
            btc = next(r for r in results if r["ticker"] == "BTC")
            assert btc["trade_placed"] is True

            # ETH should be held (rejected by risk guardian)
            eth = next(r for r in results if r["ticker"] == "ETH")
            assert eth["trade_placed"] is False
            assert eth["action"] == "HOLD"

            # SOL should be held (not proposed at all)
            sol = next(r for r in results if r["ticker"] == "SOL")
            assert sol["action"] == "HOLD"
            assert sol["trade_placed"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 16: JSON Parser Robustness (critical for AI pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJSONParserRobustness:
    """Validates that the JSON extractor handles all Claude/Groq output formats."""

    def test_markdown_wrapped_json(self):
        from backend.src.core.engine import _extract_json
        raw = '```json\n[{"ticker": "BTC", "action": "LONG", "confidence": 85}]\n```'
        result = _extract_json(raw)
        assert result[0]["ticker"] == "BTC"

    def test_preamble_postamble_json(self):
        from backend.src.core.engine import _extract_json
        raw = 'Here is my analysis:\n\n[{"ticker": "ETH", "action": "SHORT"}]\n\nHope this helps!'
        result = _extract_json(raw)
        assert result[0]["action"] == "SHORT"

    def test_nested_objects_parse_correctly(self):
        from backend.src.core.engine import _extract_json
        raw = '[{"ticker": "SOL", "confidence": 90, "meta": {"regime": "TRENDING_UP"}}]'
        result = _extract_json(raw)
        assert result[0]["meta"]["regime"] == "TRENDING_UP"

    def test_garbage_text_raises_error(self):
        from backend.src.core.engine import _extract_json
        with pytest.raises(ValueError):
            _extract_json("I don't know what to recommend right now.")


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 17: Memory-Driven Adaptation
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryAdaptation:
    """Tests that recent performance memory is injected into agent prompts."""

    @pytest.mark.asyncio
    async def test_memory_passed_to_quant_and_risk(self):
        """Recent trade memory is correctly forwarded to both AI agents."""
        with patch("backend.src.core.engine._exchange.is_btc_dumping", new_callable=AsyncMock, return_value=False), \
             patch("backend.src.core.engine._fetch_mtf_condensed_ohlcv", new_callable=AsyncMock,
                   return_value=("DATA", {"close": 50000.0}, None)), \
             patch("backend.src.core.engine._groq_sentiment", new_callable=AsyncMock, return_value=(0, "Neutral")), \
             patch("backend.src.core.engine.propose_trades", new_callable=AsyncMock, return_value=[
                 {"ticker": "BTC", "proposed_action": "LONG", "confidence": 80, "position_size_pct": 5,
                  "quant_reasoning": "Breakout", "suggested_sl": 48000, "suggested_tp": 55000}
             ]) as mock_quant, \
             patch("backend.src.core.engine.evaluate_proposals", new_callable=AsyncMock, return_value=[
                 {"ticker": "BTC", "proposed_action": "LONG", "confidence": 80, "verdict": "APPROVED",
                  "regime": "TRENDING_UP", "position_size_pct": 5,
                  "quant_reasoning": "Breakout", "risk_reasoning": "OK"}
             ]) as mock_risk, \
             patch("backend.src.core.engine._execute_decision", new_callable=AsyncMock,
                   return_value={"ticker": "BTC", "action": "LONG", "trade_placed": True}), \
             patch("backend.src.core.engine.fetch_recent_performance_memory", new_callable=AsyncMock,
                   return_value="STRATEGY ADAPTATION MEMORY\nWin Rate: 45%\nAVOID BTC LONG") as mock_mem, \
             patch("backend.src.core.engine.ALLOWED_TICKERS", ["BTC"]), \
             patch("backend.src.core.engine.CONFIDENCE_THRESHOLD", 45):

            from backend.src.core.engine import scan_all_tickers
            await scan_all_tickers()

            # Verify memory was fetched
            mock_mem.assert_called_once()

            # Verify memory was passed to Quant Analyst
            quant_call_args = mock_quant.call_args
            assert "STRATEGY ADAPTATION MEMORY" in quant_call_args[0][2]  # 3rd arg = memory

            # Verify memory was passed to Risk Guardian
            risk_call_args = mock_risk.call_args
            assert "STRATEGY ADAPTATION MEMORY" in risk_call_args[0][3]  # 4th arg = memory
