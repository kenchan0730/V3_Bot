import csv

import pytest

from core.blotter import FIELDS, Blotter


@pytest.fixture
def blotter(tmp_path):
    return Blotter(str(tmp_path / "blotter.csv"))


def read_rows(blotter):
    with open(blotter.path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_header_written_on_init(blotter):
    with open(blotter.path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == FIELDS


def test_log_signal(blotter):
    signal = {"action": "STRONG_BUY", "entry": 12.0, "stop": 11.0, "target1": 14.0, "reason": "hammer"}
    blotter.log_signal("AVAH", signal, {"z_score": 1.1, "rsi": 55.0}, vol_ratio=1.7, exposure_pct=75)
    row = read_rows(blotter)[0]
    assert row["event_type"] == "SIGNAL"
    assert row["symbol"] == "AVAH"
    assert row["signal"] == "STRONG_BUY"
    assert row["z_score"] == "1.1"
    assert row["exposure_pct"] == "75"


def test_log_rejection(blotter):
    blotter.log_rejection("QXO", "購買力不足", stage="PRE_TRADE")
    row = read_rows(blotter)[0]
    assert row["event_type"] == "REJECT_PRE_TRADE"
    assert row["reason"] == "購買力不足"


def test_log_order(blotter):
    blotter.log_order("AVAH", "BUY", 10, 42, 12.0, 11.0, 14.0, reason="bracket")
    row = read_rows(blotter)[0]
    assert row["event_type"] == "ORDER"
    assert row["order_id"] == "42"
    assert row["stop_price"] == "11.0"
    assert row["status"] == "SUBMITTED"


def test_log_fill(blotter):
    blotter.log_fill("AVAH", "SELL", 10, 13.5, 42, realized_pnl=15.0)
    row = read_rows(blotter)[0]
    assert row["event_type"] == "FILL"
    assert row["fill_price"] == "13.5"
    assert row["realized_pnl"] == "15.0"


def test_log_event_with_extras(blotter):
    blotter.log_event("HALT", reason="daily loss", shares=0)
    row = read_rows(blotter)[0]
    assert row["event_type"] == "HALT"
    assert row["reason"] == "daily loss"


def test_appends_are_cumulative(blotter):
    blotter.log_event("STARTUP", reason="a")
    blotter.log_event("SHUTDOWN", reason="b")
    rows = read_rows(blotter)
    assert len(rows) == 2
    assert [r["event_type"] for r in rows] == ["STARTUP", "SHUTDOWN"]


def test_reopening_preserves_history(tmp_path):
    path = str(tmp_path / "blotter.csv")
    Blotter(path).log_event("STARTUP", reason="first")
    second = Blotter(path)
    second.log_event("STARTUP", reason="second")
    assert len(read_rows(second)) == 2


def test_timestamps_present(blotter):
    blotter.log_event("STARTUP")
    row = read_rows(blotter)[0]
    assert row["timestamp_utc"]
    assert row["timestamp_local"]


def test_unknown_keys_ignored(blotter):
    blotter.log_event("CUSTOM", reason="x", not_a_field="ignored")
    row = read_rows(blotter)[0]
    assert "not_a_field" not in row
    assert row["event_type"] == "CUSTOM"
