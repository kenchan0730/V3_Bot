import pytest

from core.risk_manager import RiskManager
from core.trading_state import TradingState


RISK_CONFIG = {
    "max_risk_percent": 2.0,
    "reduced_risk_percent": 1.0,
    "max_loss_streak": 3,
    "max_position_pct": 50.0,
    "max_drawdown_limit": 10.0,
    "max_absolute_loss": 8.0,
    "daily_loss_limit": 2.0,
    "vix_threshold": 25,
    "vix_risk_cap": 1.5,
}


@pytest.fixture
def risk_mgr():
    return RiskManager(initial_capital=1000.0, config=RISK_CONFIG,
                       state=TradingState(initial_capital=1000.0))


# ----- config enforcement (H10) -----

def test_config_values_are_applied():
    mgr = RiskManager(initial_capital=1000.0, config={
        "max_risk_percent": 3.0,
        "max_drawdown_limit": 15.0,
        "max_absolute_loss": 12.0,
        "daily_loss_limit": 4.0,
        "max_position_pct": 25.0,
    })
    assert mgr.max_risk_pct == 3.0
    assert mgr.max_drawdown_limit == 15.0
    assert mgr.max_absolute_loss == 12.0
    assert mgr.daily_loss_limit == 4.0
    assert mgr.max_position_pct == 25.0


def test_drawdown_uses_configured_limit():
    mgr = RiskManager(initial_capital=1000.0, config={"max_drawdown_limit": 5.0, "max_absolute_loss": 90.0})
    mgr.peak_capital = 1000.0
    mgr.total_capital = 930.0
    ok, msg = mgr.check_drawdown()
    assert ok is False and "5.0%" in msg


def test_absolute_loss_uses_configured_limit():
    mgr = RiskManager(initial_capital=1000.0, config={"max_drawdown_limit": 99.0, "max_absolute_loss": 5.0})
    mgr.total_capital = 900.0
    ok, msg = mgr.check_drawdown()
    assert ok is False and "絕對虧損" in msg


def test_position_size_respects_concentration_cap():
    mgr = RiskManager(initial_capital=1000.0, config={"max_risk_percent": 50.0, "max_position_pct": 10.0})
    shares = mgr.calculate_position_size(10.0, 9.0, price_limit=40, max_shares=1000)
    assert shares == 10  # 10% of 1000 / $10


# ----- sizing -----

def test_calculate_position_size_basic(risk_mgr):
    shares = risk_mgr.calculate_position_size(20.0, 18.0, price_limit=40, max_shares=20)
    assert 0 < shares <= 20


def test_calculate_position_size_invalid_stop(risk_mgr):
    assert risk_mgr.calculate_position_size(20.0, 21.0) == 0


def test_calculate_position_size_above_price_limit(risk_mgr):
    assert risk_mgr.calculate_position_size(100.0, 90.0, price_limit=40) == 0


# ----- daily loss (H1) -----

def test_check_daily_loss_accumulates(risk_mgr):
    ok, _ = risk_mgr.check_daily_loss(-5.0)
    assert ok is True
    assert risk_mgr.get_daily_pnl() == -5.0


def test_check_daily_loss_blocks_beyond_limit(risk_mgr):
    ok, msg = risk_mgr.check_daily_loss(-25.0)
    assert ok is False and "限額" in msg


def test_is_within_daily_loss_limit_blocks(risk_mgr):
    risk_mgr.daily_loss = -25.0
    ok, msg = risk_mgr.is_within_daily_loss_limit()
    assert ok is False and "限額" in msg


def test_is_within_daily_loss_limit_zero_capital(risk_mgr):
    risk_mgr.total_capital = 0
    ok, _ = risk_mgr.is_within_daily_loss_limit()
    assert ok is True


# ----- streak policy -----

def test_loss_streak_reduces_risk(risk_mgr):
    for _ in range(3):
        risk_mgr.record_trade(-10.0)
    assert risk_mgr.current_risk_pct == 1.0


def test_win_resets_streak(risk_mgr):
    risk_mgr.record_trade(-10.0)
    risk_mgr.record_trade(20.0)
    assert risk_mgr.consecutive_losses == 0
    assert risk_mgr.current_risk_pct == 2.0


def test_record_trade_updates_capital(risk_mgr):
    risk_mgr.record_trade(50.0)
    assert risk_mgr.total_capital == 1050.0
    risk_mgr.record_trade(-30.0)
    assert risk_mgr.consecutive_losses == 1


# ----- vix -----

def test_check_vix_reduces_risk(risk_mgr):
    risk_mgr.check_vix(30.0)
    assert risk_mgr.current_risk_pct <= 1.5


def test_check_vix_calm_market(risk_mgr):
    assert risk_mgr.check_vix(15.0) == 2.0


# ----- capital / state -----

def test_update_capital_tracks_peak(risk_mgr):
    risk_mgr.update_capital(1100.0)
    assert risk_mgr.peak_capital == 1100.0


def test_check_drawdown_blocks_on_absolute_loss(risk_mgr):
    risk_mgr.total_capital = 900.0
    ok, msg = risk_mgr.check_drawdown()
    assert ok is False and "絕對虧損" in msg


def test_get_daily_pnl_returns_tracked_value(risk_mgr):
    risk_mgr.daily_loss = -12.5
    assert risk_mgr.get_daily_pnl() == -12.5


def test_shared_state_with_emotion_manager():
    state = TradingState(initial_capital=1000.0)
    mgr = RiskManager(initial_capital=1000.0, config=RISK_CONFIG, state=state)
    mgr.record_trade(-10.0)
    assert state.consecutive_losses == 1
    assert state.today_trades == 1


def test_is_market_open_returns_bool():
    assert isinstance(RiskManager.is_market_open(), bool)
