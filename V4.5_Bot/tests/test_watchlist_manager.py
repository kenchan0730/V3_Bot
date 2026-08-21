"""Tests for tiered watchlist manager."""

import json
from pathlib import Path

import pytest

from core.watchlist_manager import WatchlistManager


@pytest.fixture
def mgr(tmp_path):
    cfg = {
        "core": ["AVAH", "QXO"],
        "satellite": ["F", "SOFI"],
        "max_active": 6,
        "max_satellite": 4,
        "refresh_hours": 0,
        "persist_file": str(tmp_path / "watchlist.json"),
        "scanner": {"enabled": False},
    }
    return WatchlistManager(cfg)


def test_core_symbols(mgr):
    assert mgr.core_symbols() == ["AVAH", "QXO"]


def test_build_default_includes_core_and_satellite(mgr):
    active = mgr._build_default()
    assert "AVAH" in active
    assert "F" in active


def test_persist_and_load(mgr, tmp_path):
    mgr._active = ["AVAH", "F"]
    mgr._save_persisted(["AVAH", "F"], meta={"test": True})
    path = Path(mgr.cfg["persist_file"])
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["active"] == ["AVAH", "F"]


def test_dedupe_correlated_keeps_priority(mgr, monkeypatch):
    def fake_matrix(closes, use_weekly=True, min_observations=8):
        import pandas as pd
        return pd.DataFrame(
            [[1.0, 0.95], [0.95, 1.0]],
            index=["A", "B"],
            columns=["A", "B"],
        )

    monkeypatch.setattr("core.watchlist_manager.correlation_matrix", fake_matrix)
    monkeypatch.setattr(
        "core.watchlist_manager.clustered_pairs",
        lambda matrix, threshold=0.8: [("A", "B", 0.95)],
    )
    monkeypatch.setattr(
        "core.watchlist_manager.yf.download",
        lambda *args, **kwargs: __import__("pandas").DataFrame({"close": [1, 2, 3]}),
    )
    result = mgr.dedupe_correlated(["A", "B", "C"])
    assert "A" in result
    assert "B" not in result or "A" not in result  # one dropped
