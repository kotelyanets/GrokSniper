import pytest

from scripts import migrate_to_live


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
        ("unexpected", False),
    ],
)
def test_is_enabled_parses_common_boolean_forms(raw, expected):
    assert migrate_to_live._is_enabled(raw) is expected
