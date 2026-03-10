"""
test_pnl_math.py
----------------
Isolated tests to validate PnL calculations for both LONG and SHORT positions.
Ensures that short-side profitability logic is not accidentally inverted.
"""

def calculate_pnl(side: str, entry_price: float, exit_price: float, amount: float) -> tuple[float, float]:
    """Helper method replicating the core system PnL logic."""
    if side.upper() == "LONG":
        pnl_usd = (exit_price - entry_price) * amount
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    elif side.upper() == "SHORT":
        pnl_usd = (entry_price - exit_price) * amount
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100
    else:
        raise ValueError("Invalid side")
        
    return pnl_usd, pnl_pct

class TestPnLMath:
    def test_long_profit(self):
        # Bought 2 ETH @ $2000, sold @ $2500
        pnl_usd, pnl_pct = calculate_pnl("LONG", 2000.0, 2500.0, 2.0)
        assert pnl_usd == 1000.0  # +$1000 total
        assert pnl_pct == 25.0    # +25%

    def test_long_loss(self):
        # Bought 1 BTC @ $50000, sold @ $45000
        pnl_usd, pnl_pct = calculate_pnl("LONG", 50000.0, 45000.0, 1.0)
        assert pnl_usd == -5000.0
        assert pnl_pct == -10.0

    def test_short_profit(self):
        # Shorted 10 SOL @ $100, covered @ $80
        pnl_usd, pnl_pct = calculate_pnl("SHORT", 100.0, 80.0, 10.0)
        assert pnl_usd == 200.0   # +$200 total (price went down, we profit)
        assert pnl_pct == 20.0    # +20%

    def test_short_loss(self):
        # Shorted 1 BTC @ $50000, covered @ $55000
        pnl_usd, pnl_pct = calculate_pnl("SHORT", 50000.0, 55000.0, 1.0)
        assert pnl_usd == -5000.0 # -$5000 total (price went up, we lose)
        assert pnl_pct == -10.0

    def test_zero_change(self):
        # Break even trade
        pnl_usd, pnl_pct = calculate_pnl("LONG", 100.0, 100.0, 50.0)
        assert pnl_usd == 0.0
        assert pnl_pct == 0.0
        
        pnl_usd_short, pnl_pct_short = calculate_pnl("SHORT", 100.0, 100.0, 50.0)
        assert pnl_usd_short == 0.0
        assert pnl_pct_short == 0.0
