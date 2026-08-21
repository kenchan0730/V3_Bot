import pandas as pd
import pytest

from core.sector_tracker import SectorTracker


def patch_download(monkeypatch, performance_by_symbol, error_symbols=()):
    """Fake yf.download returning a 2-bar frame implying a given % move."""

    def fake_download(symbol, period=None, interval=None, progress=None):
        if symbol in error_symbols:
            raise RuntimeError("download failed")
        change = performance_by_symbol.get(symbol, 0.0)
        start = 100.0
        end = start * (1 + change / 100)
        return pd.DataFrame({"Close": [start, end]})

    monkeypatch.setattr("core.sector_tracker.yf.download", fake_download)


def test_relative_strength_against_spy(monkeypatch):
    patch_download(monkeypatch, {"SPY": 1.0, "XLK": 3.0, "XLE": -2.0, "XLV": 1.0, "SMH": 5.0})
    relative = SectorTracker.get_relative_strength("5d")
    assert relative["Technology"] == pytest.approx(2.0, abs=0.01)
    assert relative["Energy"] == pytest.approx(-3.0, abs=0.01)
    assert relative["Semiconductor"] == pytest.approx(4.0, abs=0.01)


def test_relative_strength_handles_download_error(monkeypatch):
    patch_download(monkeypatch, {"SPY": 1.0}, error_symbols={"XLK"})
    relative = SectorTracker.get_relative_strength("5d")
    assert relative["Technology"] == 0


def test_relative_strength_handles_spy_error(monkeypatch):
    patch_download(monkeypatch, {"XLK": 2.0}, error_symbols={"SPY"})
    relative = SectorTracker.get_relative_strength("5d")
    assert relative["Technology"] == pytest.approx(2.0, abs=0.01)


def test_sector_rating_full_weight_when_strong(monkeypatch):
    patch_download(monkeypatch, {"SPY": 0.0, "XLK": 2.0, "XLE": 2.0, "XLV": 2.0, "SMH": 2.0})
    rating = SectorTracker.get_sector_rating()
    assert rating["weights"]["Technology"] == 100
    assert rating["alerts"] == []


def test_sector_rating_reduces_weak_sector(monkeypatch):
    patch_download(monkeypatch, {"SPY": 5.0, "XLK": 0.0, "XLE": 0.0, "XLV": 0.0, "SMH": 0.0})
    rating = SectorTracker.get_sector_rating()
    assert rating["weights"]["Technology"] < 100
    assert rating["weights"]["Technology"] >= 50


def test_sector_rating_flags_semis_lagging(monkeypatch):
    patch_download(monkeypatch, {"SPY": 0.0, "XLK": 1.0, "XLE": 1.0, "XLV": 1.0, "SMH": -8.0})
    rating = SectorTracker.get_sector_rating()
    assert any("SMH" in alert for alert in rating["alerts"])


def test_sector_rating_covers_all_sectors(monkeypatch):
    patch_download(monkeypatch, {"SPY": 0.0})
    rating = SectorTracker.get_sector_rating()
    assert set(rating["weights"]) == set(SectorTracker.SECTORS.values())


def test_weights_are_floored_at_fifty(monkeypatch):
    patch_download(monkeypatch, {"SPY": 50.0, "XLK": -50.0, "XLE": -50.0, "XLV": -50.0, "SMH": -50.0})
    rating = SectorTracker.get_sector_rating()
    assert all(weight >= 50 for weight in rating["weights"].values())


def test_handles_multiindex_columns(monkeypatch):
    """yfinance >=1.0 returns MultiIndex columns; scalars must still be derived."""

    def fake_download(symbol, period=None, interval=None, progress=None):
        columns = pd.MultiIndex.from_product([["Close", "Open"], [symbol]])
        return pd.DataFrame([[100.0, 100.0], [102.0, 101.0]], columns=columns)

    monkeypatch.setattr("core.sector_tracker.yf.download", fake_download)
    relative = SectorTracker.get_relative_strength("5d")
    assert relative["Technology"] == pytest.approx(0.0, abs=0.01)


def test_handles_empty_frame(monkeypatch):
    monkeypatch.setattr("core.sector_tracker.yf.download",
                        lambda *a, **k: pd.DataFrame())
    relative = SectorTracker.get_relative_strength("5d")
    assert all(value == 0 for value in relative.values())


def test_period_return_handles_zero_first_price(monkeypatch):
    monkeypatch.setattr("core.sector_tracker.yf.download",
                        lambda *a, **k: pd.DataFrame({"Close": [0.0, 10.0]}))
    assert SectorTracker._period_return_pct("XLK", "5d") is None
