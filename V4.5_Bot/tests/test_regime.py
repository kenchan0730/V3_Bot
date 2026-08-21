"""Tests for market regime detection."""

import pytest

from core.regime import CRISIS, NEUTRAL, RISK_OFF, RISK_ON, RegimeDetector


@pytest.fixture
def detector():
    return RegimeDetector({
        "enabled": True,
        "vix_risk_on": 18,
        "vix_risk_off": 28,
        "vix_crisis": 35,
        "breadth_risk_on": 65,
        "breadth_risk_off": 30,
    })


def test_risk_on_regime(detector, monkeypatch):
    monkeypatch.setattr(
        "core.regime.fetch_macro_snapshot",
        lambda ttl=300: {
            "spy_above_ma50": True,
            "spy_above_ma200": True,
            "credit_trend_pct": 1.0,
            "vix_term_spread": -1.0,
        },
    )
    result = detector.detect(vix=15, breadth_score=75)
    assert result.regime == RISK_ON
    assert result.allow_new_entries is True
    assert result.exposure_pct >= 90


def test_risk_off_regime(detector, monkeypatch):
    monkeypatch.setattr(
        "core.regime.fetch_macro_snapshot",
        lambda ttl=300: {
            "spy_above_ma50": False,
            "spy_above_ma200": False,
            "credit_trend_pct": -3.0,
            "vix_term_spread": 4.0,
        },
    )
    result = detector.detect(vix=30, breadth_score=25)
    assert result.regime in (RISK_OFF, CRISIS)
    assert result.allow_new_entries is False


def test_crisis_on_extreme_vix(detector, monkeypatch):
    monkeypatch.setattr(
        "core.regime.fetch_macro_snapshot",
        lambda ttl=300: {"spy_above_ma50": False, "spy_above_ma200": False},
    )
    result = detector.detect(vix=40, breadth_score=10)
    assert result.regime == CRISIS
    assert result.exposure_pct == 0


def test_disabled_regime():
    det = RegimeDetector({"enabled": False})
    result = det.detect(vix=50, breadth_score=10)
    assert result.regime == NEUTRAL
