import pytest

from core.signal_utils import parse_confidence


@pytest.mark.parametrize("value,expected", [
    ("HIGH", 0.85),
    ("MEDIUM", 0.55),
    ("LOW", 0.30),
    (0.7, 0.7),
    ("0.65", 0.65),
    (None, 0.5),
    ("", 0.5),
    ("UNKNOWN", 0.5),
])
def test_parse_confidence(value, expected):
    assert parse_confidence(value, default=0.5) == pytest.approx(expected)
