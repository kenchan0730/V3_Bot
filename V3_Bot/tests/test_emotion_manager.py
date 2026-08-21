import pytest

from core.emotion_manager import EmotionManager
from core.risk_manager import RiskManager
from core.trading_state import TradingState


@pytest.fixture
def state():
    return TradingState(initial_capital=1000.0)


def test_allows_trading_when_calm(state):
    emotion = EmotionManager(state=state)
    ok, message = emotion.check_before_trade()
    assert ok is True and message == "情緒正常"


def test_blocks_after_loss_streak(state):
    emotion = EmotionManager(state=state, max_loss_streak=3)
    for _ in range(3):
        emotion.record_trade(-10.0)
    ok, message = emotion.check_before_trade()
    assert ok is False and "止蝕" in message


def test_blocks_after_daily_trade_cap(state):
    emotion = EmotionManager(state=state, max_daily_trades=2)
    emotion.record_trade(5.0)
    emotion.record_trade(5.0)
    ok, message = emotion.check_before_trade()
    assert ok is False and "今日已交易" in message


def test_win_resets_streak(state):
    emotion = EmotionManager(state=state)
    emotion.record_trade(-10.0)
    emotion.record_trade(10.0)
    assert emotion.consecutive_losses == 0


def test_config_overrides_defaults(state):
    emotion = EmotionManager(state=state, config={"max_daily_trades": 1, "max_loss_streak": 1})
    emotion.record_trade(1.0)
    ok, _ = emotion.check_before_trade()
    assert ok is False


def test_state_is_shared_with_risk_manager(state):
    emotion = EmotionManager(state=state)
    risk_mgr = RiskManager(initial_capital=1000.0, state=state)

    risk_mgr.record_trade(-20.0)
    assert emotion.consecutive_losses == 1
    assert emotion.today_trades == 1

    emotion.record_trade(-5.0)
    assert risk_mgr.consecutive_losses == 2


def test_setters_write_through_to_state(state):
    emotion = EmotionManager(state=state)
    emotion.today_trades = 7
    emotion.consecutive_losses = 2
    assert state.today_trades == 7
    assert state.consecutive_losses == 2


def test_reset_daily_clears_counters(state):
    from datetime import date, timedelta

    emotion = EmotionManager(state=state)
    emotion.record_trade(-5.0)
    state.trading_day = (date.today() - timedelta(days=1)).isoformat()
    emotion.reset_daily()
    assert emotion.today_trades == 0


def test_standalone_manager_creates_own_state():
    emotion = EmotionManager()
    emotion.record_trade(-1.0)
    assert emotion.consecutive_losses == 1
