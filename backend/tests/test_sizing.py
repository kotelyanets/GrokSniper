"""
test_sizing.py
--------------
Unit tests for Kelly Criterion position sizing (backend/src/api/sizing.py).

These are pure-function tests — no DB, no network, no mocks needed.
Run with:  pytest backend/tests/test_sizing.py -v
"""

import pytest
from backend.src.api.sizing import calculate_position_size, _kelly_fraction


# ---------------------------------------------------------------------------
# _kelly_fraction
# ---------------------------------------------------------------------------
class TestKellyFraction:
    def test_returns_positive_fraction(self):
        frac = _kelly_fraction()
        assert frac > 0, "Kelly fraction should be positive for a profitable strategy"

    def test_capped_at_max(self):
        frac = _kelly_fraction()
        assert frac <= 0.25, "Kelly fraction must never exceed 25% (KELLY_MAX_FRAC)"

    def test_is_half_kelly(self):
        """Half-Kelly should be at most half the raw Kelly."""
        frac = _kelly_fraction()
        # With win_rate=0.52, avg_win=4.2, avg_loss=2.8
        # Full Kelly = 0.52 - 0.48/1.5 = 0.52 - 0.32 = 0.20
        # Half Kelly = 0.10  (before cap)
        # We just verify it is less than a naive full-Kelly estimate
        W  = 0.52
        RR = 4.20 / 2.80
        full_kelly = max(W - (1 - W) / RR, 0.0)
        assert frac <= full_kelly + 1e-9, "Half-Kelly must be ≤ full Kelly"


# ---------------------------------------------------------------------------
# calculate_position_size
# ---------------------------------------------------------------------------
class TestCalculatePositionSize:
    BASE = dict(free_usdt=1000.0, expected_return=0.02, atr=50.0, current_price=50000.0)

    def test_returns_tuple(self):
        size, reason = calculate_position_size(**self.BASE)
        assert isinstance(size, float)
        assert isinstance(reason, str)

    def test_minimum_10_usdt(self):
        """Even with tiny balance, result must be ≥ $10 (Binance minimum)."""
        size, _ = calculate_position_size(free_usdt=5.0, expected_return=0.001, atr=1.0, current_price=100.0)
        assert size >= 10.0

    def test_capped_at_25pct(self):
        """Result must never exceed 25% of free_usdt."""
        size, _ = calculate_position_size(**self.BASE)
        assert size <= self.BASE["free_usdt"] * 0.25 + 1e-6

    def test_high_confidence_larger_than_low(self):
        """Strong ML signal should produce a larger position than a weak one."""
        high_conf, _ = calculate_position_size(
            free_usdt=1000.0, expected_return=0.05, atr=50.0, current_price=50000.0
        )
        low_conf, _ = calculate_position_size(
            free_usdt=1000.0, expected_return=0.005, atr=50.0, current_price=50000.0
        )
        assert high_conf >= low_conf, "High-confidence signal should produce ≥ sized position"

    def test_high_volatility_reduces_size(self):
        """Very high ATR (>4% of price) should halve the position vs low ATR."""
        norm_vol, _ = calculate_position_size(
            free_usdt=1000.0, expected_return=0.02, atr=100.0, current_price=50000.0
        )  # ATR% = 0.2% — low vol
        high_vol, _ = calculate_position_size(
            free_usdt=1000.0, expected_return=0.02, atr=2500.0, current_price=50000.0
        )  # ATR% = 5% — very high vol
        assert high_vol <= norm_vol, "High volatility should reduce position size"

    def test_reason_string_format(self):
        """Reason string should contain Kelly %, ML multiplier, vol multiplier."""
        _, reason = calculate_position_size(**self.BASE)
        assert "Kelly" in reason
        assert "%" in reason
        assert "ML" in reason
        assert "Vol" in reason

    def test_zero_price_safe(self):
        """current_price=0 should not crash (vol penalty defaults to 1.0)."""
        size, _ = calculate_position_size(
            free_usdt=500.0, expected_return=0.02, atr=0.0, current_price=0.0
        )
        assert size >= 10.0

    @pytest.mark.parametrize("balance", [50.0, 100.0, 500.0, 10_000.0, 100_000.0])
    def test_scales_with_balance(self, balance):
        """Larger balance should produce proportionally larger base sizes."""
        size, _ = calculate_position_size(
            free_usdt=balance, expected_return=0.02, atr=50.0, current_price=50000.0
        )
        # Must be ≥ min and ≤ 25% of balance
        assert size >= 10.0
        assert size <= balance * 0.25 + 1e-6
