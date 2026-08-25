from datetime import datetime, timedelta

import pytest

from core.external_signals import ExternalSignal, ExternalSignalInbox


def inbox(tmp_path, **overrides):
    cfg = {"enabled": True, "directory": str(tmp_path), **overrides}
    return ExternalSignalInbox(cfg)


def test_submit_then_poll_round_trip(tmp_path):
    box = inbox(tmp_path)
    box.submit({"symbol": "avah", "note": "Q3 beat", "action_hint": "buy"})
    pending = box.poll()
    assert len(pending) == 1
    assert pending[0].symbol == "AVAH"
    assert pending[0].action_hint == "BUY"


def test_symbol_is_required(tmp_path):
    with pytest.raises(ValueError):
        inbox(tmp_path).submit({"note": "no symbol"})


def test_unknown_action_hint_falls_back_to_review(tmp_path):
    box = inbox(tmp_path)
    signal = box.submit({"symbol": "AVAH", "action_hint": "YOLO"})
    assert signal.action_hint == "REVIEW"


def test_allowed_symbols_rejects_others(tmp_path):
    box = inbox(tmp_path, allowed_symbols=["AVAH"])
    box.submit({"symbol": "AVAH"})
    with pytest.raises(ValueError):
        box.submit({"symbol": "TSLA"})


def test_processed_signals_are_not_returned_twice(tmp_path):
    box = inbox(tmp_path)
    signal = box.submit({"symbol": "AVAH", "note": "idea"})
    box.mark_processed(signal.id)
    assert box.poll() == []


def test_stale_signals_are_dropped(tmp_path):
    box = inbox(tmp_path, max_age_hours=1)
    old = (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds")
    box.submit({"symbol": "AVAH", "note": "old idea", "received_at": old})
    assert box.poll() == []


def test_max_per_cycle_limits_batch(tmp_path):
    box = inbox(tmp_path, max_per_cycle=2)
    for i in range(5):
        box.submit({"symbol": "AVAH", "note": f"idea {i}"})
    assert len(box.poll()) == 2


def test_disabled_inbox_polls_nothing(tmp_path):
    box = inbox(tmp_path, enabled=False)
    box.submit({"symbol": "AVAH"})
    assert box.poll() == []


def test_verdicts_are_appended_and_readable(tmp_path):
    box = inbox(tmp_path)
    signal = box.submit({"symbol": "AVAH", "note": "idea"})
    box.write_verdict(signal, {"verdict": "BUY", "explanation": "looks fine"})
    stored = box.verdicts()
    assert stored[-1]["symbol"] == "AVAH"
    assert stored[-1]["verdict"] == "BUY"


def test_malformed_lines_are_skipped(tmp_path):
    box = inbox(tmp_path)
    box.submit({"symbol": "AVAH", "note": "good"})
    with box.inbox_path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    assert len(box.poll()) == 1


def test_claim_text_merges_note_and_headline():
    signal = ExternalSignal.from_dict(
        {"symbol": "AVAH", "note": "contract win", "payload": {"headline": "federal deal"}}
    )
    assert "contract win" in signal.claim_text
    assert "federal deal" in signal.claim_text


def test_same_content_gets_a_stable_id():
    payload = {"symbol": "AVAH", "note": "x", "received_at": "2026-08-24T10:00:00"}
    assert ExternalSignal.from_dict(payload).id == ExternalSignal.from_dict(payload).id
