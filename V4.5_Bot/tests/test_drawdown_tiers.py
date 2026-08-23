"""Two independent halt lines plus a de-risking warning band."""

import pytest

from core.risk_manager import RiskManager

CONFIG = {
    "max_risk_percent": 1.5,
    "reduced_risk_percent": 1.0,
    "max_drawdown_limit": 12.0,
    "max_absolute_loss": 8.0,
    "drawdown_warning_pct": 6.0,
    "drawdown_warning_risk_pct": 0.75,
}


def make_manager(capital=1275.0):
    return RiskManager(initial_capital=capital, config=CONFIG)


def test_healthy_account_is_ok():
    mgr = make_manager()
    assert mgr.drawdown_state()["level"] == "OK"
    assert mgr.check_drawdown() == (True, "OK")


def test_warning_band_reduces_risk_without_halting():
    mgr = make_manager()
    mgr.peak_capital = 1400.0
    mgr.total_capital = 1300.0          # 7.1% off peak, 1.9% off initial
    state = mgr.drawdown_state()
    assert state["level"] == "WARNING"

    ok, _ = mgr.check_drawdown()
    assert ok is True
    assert mgr.current_risk_pct == pytest.approx(0.75)


def test_peak_drawdown_halts_even_when_profitable():
    mgr = make_manager()
    mgr.peak_capital = 1600.0
    mgr.total_capital = 1380.0          # 13.8% off peak but still above initial
    state = mgr.drawdown_state()
    assert state["level"] == "HALT"
    assert "高位回撤" in state["message"]
    assert state["absolute_loss_pct"] < 0


def test_absolute_loss_halts_before_wide_drawdown_limit():
    mgr = make_manager()
    mgr.peak_capital = 1275.0
    mgr.total_capital = 1160.0          # 9.0% off both peak and initial
    state = mgr.drawdown_state()
    assert state["level"] == "HALT"
    assert "絕對虧損" in state["message"]


def test_two_lines_are_genuinely_distinct():
    """A loss that trips absolute-loss must not also trip peak drawdown."""
    mgr = make_manager()
    mgr.peak_capital = 1275.0
    mgr.total_capital = 1160.0
    assert mgr.absolute_loss_pct() > mgr.max_absolute_loss
    assert mgr.drawdown_pct() < mgr.max_drawdown_limit


def test_drawdown_state_reports_both_metrics():
    mgr = make_manager()
    mgr.peak_capital = 1500.0
    mgr.total_capital = 1275.0
    state = mgr.drawdown_state()
    assert state["drawdown_pct"] == pytest.approx(15.0)
    assert state["absolute_loss_pct"] == pytest.approx(0.0)
