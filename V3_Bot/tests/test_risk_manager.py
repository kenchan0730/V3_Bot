import pytest

from core.risk_manager import RiskManager


@pytest.fixture
def risk_mgr():
    return RiskManager(initial_capital=1000.0, max_risk_pct=2.0, daily_loss_limit=2.0)


def test_calculate_position_size_basic(risk_mgr):
    shares = risk_mgr.calculate_position_size(20.0, 18.0, price_limit=40, max_shares=20)
    assert shares > 0
    assert shares <= 20


def test_calculate_position_size_invalid_stop(risk_mgr):
    shares = risk_mgr.calculate_position_size(20.0, 21.0)
    assert shares == 0


def test_check_daily_loss_accumulates(risk_mgr):
    ok, _ = risk_mgr.check_daily_loss(-5.0)
    assert ok is True
    assert risk_mgr.get_daily_pnl() == -5.0


def test_is_within_daily_loss_limit_blocks(risk_mgr):
    risk_mgr.daily_loss = -25.0
    ok, msg = risk_mgr.is_within_daily_loss_limit()
    assert ok is False
    assert "限額" in msg


def test_check_vix_reduces_risk(risk_mgr):
    risk_mgr.check_vix(30.0)
    assert risk_mgr.current_risk_pct <= 1.5


def test_is_market_open_weekday_logic():
    assert isinstance(RiskManager.is_market_open(), bool)


def test_record_trade_updates_capital(risk_mgr):
    risk_mgr.record_trade(50.0)
    assert risk_mgr.total_capital == 1050.0
    risk_mgr.record_trade(-30.0)
    assert risk_mgr.consecutive_losses == 1


def test_update_capital_tracks_peak(risk_mgr):
    risk_mgr.update_capital(1100.0)
    assert risk_mgr.peak_capital == 1100.0


def test_check_drawdown_blocks_on_absolute_loss(risk_mgr):
    risk_mgr.total_capital = 900.0
    ok, msg = risk_mgr.check_drawdown()
    assert ok is False
    assert "絕對虧損" in msg


def test_get_daily_pnl_returns_tracked_value(risk_mgr):
    risk_mgr.daily_loss = -12.5
    assert risk_mgr.get_daily_pnl() == -12.5
