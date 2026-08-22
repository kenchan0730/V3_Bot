import pytest

from core.position_sizer import compute_atr, fractional_kelly_shares, risk_of_ruin_approx
from tests.helpers import make_ohlcv


def test_compute_atr():
    closes = [10 + i * 0.1 for i in range(30)]
    df = make_ohlcv(closes)
    atr = compute_atr(df, period=14)
    assert atr is not None
    assert atr > 0


def test_fractional_kelly_caps_size():
    shares = fractional_kelly_shares(0.55, 2.0, 1.0, 10.0, 1000, fraction=0.25)
    assert 0 < shares < 100


def test_risk_of_ruin_lower_with_edge():
    bad = risk_of_ruin_approx(0.4, 1.0, 2.0)
    good = risk_of_ruin_approx(0.55, 1.5, 1.0)
    assert good < bad
