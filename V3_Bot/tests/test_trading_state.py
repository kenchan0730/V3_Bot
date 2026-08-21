import json
from datetime import date, timedelta

import pytest

from core.trading_state import SCHEMA_VERSION, TradingState


@pytest.fixture
def state(tmp_path):
    return TradingState(initial_capital=1000.0, state_file=str(tmp_path / "state.json"))


def test_initial_values(state):
    assert state.total_capital == 1000.0
    assert state.peak_capital == 1000.0
    assert state.daily_realized_pnl == 0.0
    assert state.halted is False


def test_record_fill_appends_ledger(state):
    entry = state.record_fill("AVAH", "BOT", 10, 12.5, realized_pnl=0.0, order_id="x1")
    assert entry["symbol"] == "AVAH"
    assert len(state.ledger) == 1
    assert state.today_trades == 1


def test_apply_realized_pnl_updates_capital_and_streak(state):
    state.apply_realized_pnl(-50.0)
    assert state.total_capital == 950.0
    assert state.daily_realized_pnl == -50.0
    assert state.consecutive_losses == 1

    state.apply_realized_pnl(30.0)
    assert state.consecutive_losses == 0
    assert state.total_realized_pnl == -20.0


def test_peak_capital_tracks_high_water(state):
    state.apply_realized_pnl(200.0)
    assert state.peak_capital == 1200.0
    state.apply_realized_pnl(-100.0)
    assert state.peak_capital == 1200.0


def test_sync_capital_from_broker(state):
    state.sync_capital(1500.0)
    assert state.total_capital == 1500.0
    assert state.peak_capital == 1500.0
    state.sync_capital(0)
    assert state.total_capital == 1500.0


def test_reset_daily_rolls_counters(state):
    state.today_trades = 3
    state.daily_realized_pnl = -20.0
    state.halt("test")
    state.trading_day = (date.today() - timedelta(days=1)).isoformat()

    assert state.reset_daily_if_needed() is True
    assert state.today_trades == 0
    assert state.daily_realized_pnl == 0.0
    assert state.halted is False


def test_reset_daily_noop_same_day(state):
    state.today_trades = 2
    assert state.reset_daily_if_needed() is False
    assert state.today_trades == 2


def test_halt_records_reason(state):
    state.halt("每日虧損")
    assert state.halted is True
    assert state.halt_reason == "每日虧損"


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    original = TradingState(initial_capital=1000.0, state_file=str(path))
    original.apply_realized_pnl(-25.0)
    original.record_fill("QXO", "BOT", 5, 20.0)
    assert original.save() is True

    restored = TradingState(initial_capital=1000.0, state_file=str(path))
    assert restored.load() is True
    assert restored.total_capital == pytest.approx(975.0)
    assert restored.total_realized_pnl == pytest.approx(-25.0)
    assert len(restored.ledger) == 1


def test_load_missing_file_returns_false(tmp_path):
    state = TradingState(state_file=str(tmp_path / "absent.json"))
    assert state.load() is False


def test_load_corrupt_file_is_safe(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    state = TradingState(initial_capital=500.0, state_file=str(path))
    assert state.load() is False
    assert state.total_capital == 500.0


def test_load_rejects_future_schema(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION + 5}), encoding="utf-8")
    state = TradingState(state_file=str(path))
    assert state.load() is False


def test_ledger_is_capped_on_save(tmp_path):
    path = tmp_path / "state.json"
    state = TradingState(state_file=str(path))
    for i in range(600):
        state.record_fill("AVAH", "BOT", 1, 10.0, order_id=str(i))
    assert len(state.to_dict()["ledger"]) == 500
