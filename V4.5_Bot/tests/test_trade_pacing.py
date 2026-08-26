from datetime import datetime, timedelta

from core.trade_pacing import TradePacer


BASE = {
    "strong_min_confluence": 4,
    "moderate_min_confluence": 3,
    "moderate_min_edges": 3,
    "rsi_max": 72.0,
    "reject_rsi_above": 78.0,
    "zscore_max": 1.45,
    "zscore_min": 0.5,
    "min_candle_strength": 0.30,
    "min_vol_ratio_high": 1.2,
    "retail_min_score": 5,
}


def pacer(**overrides):
    cfg = {"target_trades_per_month": 8, "state_file": None, **overrides}
    return TradePacer(cfg, state_file=None)


def test_no_trades_means_behind_and_relaxed():
    status = pacer().status(now=datetime(2026, 8, 1))
    assert status.state == "BEHIND"
    assert status.relax_level > 0


def test_on_track_leaves_thresholds_untouched():
    p = pacer()
    now = datetime(2026, 8, 20)
    for day in range(7):
        p.record_entry(now - timedelta(days=day * 3), persist=False)
    adjusted, status = p.apply(BASE, now=now)
    assert status.state == "ON_TRACK"
    assert adjusted == BASE


def test_behind_pace_relaxes_soft_gates_only():
    adjusted, status = pacer().apply(BASE, now=datetime(2026, 8, 1))
    assert status.state == "BEHIND"
    assert adjusted["strong_min_confluence"] <= BASE["strong_min_confluence"]
    assert adjusted["rsi_max"] >= BASE["rsi_max"]
    assert adjusted["zscore_min"] <= BASE["zscore_min"]


def test_relaxation_respects_floors():
    p = pacer(target_trades_per_month=40, max_relax_level=1.0)
    adjusted, _ = p.apply(BASE, now=datetime(2026, 8, 1))
    assert adjusted["strong_min_confluence"] >= 3
    assert adjusted["zscore_min"] >= 0.30
    assert adjusted["min_candle_strength"] >= 0.20
    assert adjusted["retail_min_score"] >= 4


def test_relaxation_respects_ceilings():
    p = pacer(target_trades_per_month=40)
    adjusted, _ = p.apply(BASE, now=datetime(2026, 8, 1))
    assert adjusted["rsi_max"] <= 78.0
    assert adjusted["reject_rsi_above"] <= 82.0
    assert adjusted["zscore_max"] <= 1.80


def test_ahead_of_pace_tightens():
    p = pacer()
    now = datetime(2026, 8, 20)
    for day in range(11):
        p.record_entry(now - timedelta(days=day), persist=False)
    adjusted, status = p.apply(BASE, now=now)
    assert status.state == "AHEAD"
    assert adjusted["strong_min_confluence"] >= BASE["strong_min_confluence"]


def test_hard_monthly_cap_blocks_new_entries():
    p = pacer(max_trades_per_month=3)
    now = datetime(2026, 8, 20)
    for day in range(3):
        p.record_entry(now - timedelta(days=day), persist=False)
    status = p.status(now=now)
    assert status.state == "CAPPED"
    assert status.allow_new_entry is False


def test_window_drops_old_entries():
    p = pacer()
    now = datetime(2026, 8, 20)
    p.record_entry(now - timedelta(days=45), persist=False)
    assert p.count_in_window(now) == 0


def test_disabled_pacer_is_neutral():
    p = pacer(enabled=False)
    adjusted, status = p.apply(BASE, now=datetime(2026, 8, 1))
    assert status.relax_level == 0.0
    assert adjusted == BASE


def test_state_round_trip(tmp_path):
    path = tmp_path / "pacing.json"
    first = TradePacer({"target_trades_per_month": 8}, state_file=str(path))
    when = datetime(2026, 8, 18, 10, 30)
    first.record_entry(when)
    second = TradePacer({"target_trades_per_month": 8}, state_file=str(path))
    assert second.count_in_window(when + timedelta(days=1)) == 1
