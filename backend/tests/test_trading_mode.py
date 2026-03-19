import pytest

from backend.src.api.trading_mode import build_trading_mode, is_enabled


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("y", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", False),
        (None, False),
    ],
)
def test_is_enabled_parses_common_values(raw, expected):
    assert is_enabled(raw) is expected


def test_build_trading_mode_live_enabled_only_when_all_flags_off():
    mode = build_trading_mode("False", "False", "False")
    assert mode["paper_trade"] is False
    assert mode["dry_run"] is False
    assert mode["binance_testnet"] is False
    assert mode["live_trading_enabled"] is True


def test_build_trading_mode_live_disabled_when_any_flag_on():
    assert build_trading_mode("True", "False", "False")["live_trading_enabled"] is False
    assert build_trading_mode("False", "True", "False")["live_trading_enabled"] is False
    assert build_trading_mode("False", "False", "True")["live_trading_enabled"] is False
