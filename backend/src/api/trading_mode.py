"""
Helpers for deriving runtime trading-mode flags from environment variables.
"""


def is_enabled(value: str | None, default: str = "False") -> bool:
    return (value or default).strip().lower() in {"true", "1", "yes", "y", "on"}


def build_trading_mode(paper_trade: str | None, dry_run: str | None, testnet: str | None) -> dict:
    paper_trade_enabled = is_enabled(paper_trade, "False")
    dry_run_enabled = is_enabled(dry_run, "False")
    testnet_enabled = is_enabled(testnet, "True")
    return {
        "paper_trade": paper_trade_enabled,
        "dry_run": dry_run_enabled,
        "binance_testnet": testnet_enabled,
        "live_trading_enabled": not (paper_trade_enabled or dry_run_enabled or testnet_enabled),
    }
