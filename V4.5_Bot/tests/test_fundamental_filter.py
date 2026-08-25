import pytest

from core.fundamental_filter import FundamentalFilter


class StubTicker:
    calls = 0

    def __init__(self, info=None, raise_error=False):
        self._info = info or {}
        self._raise = raise_error

    @property
    def info(self):
        StubTicker.calls += 1
        if self._raise:
            raise RuntimeError("yfinance down")
        return self._info

    @property
    def calendar(self):
        return {"Earnings Date": "2026-09-01"}


GOOD_INFO = {
    "marketCap": 5_000_000_000,
    "averageVolume": 3_000_000,
    "trailingPE": 18.0,
    "earningsGrowth": 0.25,
}


def patch_ticker(monkeypatch, info=None, raise_error=False):
    StubTicker.calls = 0
    monkeypatch.setattr(
        "core.fundamental_filter.yf.Ticker",
        lambda symbol: StubTicker(info, raise_error),
    )


@pytest.fixture
def filt():
    return FundamentalFilter({"enabled": True})


def test_disabled_filter_passes_everything():
    passed, reason = FundamentalFilter({"enabled": False}).filter("AVAH")
    assert passed is True and "關閉" in reason


def test_passes_quality_stock(monkeypatch, filt):
    patch_ticker(monkeypatch, GOOD_INFO)
    passed, reason = filt.filter("AAPL")
    assert passed is True and "合格" in reason


def test_rejects_small_market_cap(monkeypatch, filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "marketCap": 1_000_000})
    passed, reason = filt.filter("TINY")
    assert passed is False and "市值" in reason


def test_rejects_thin_volume(monkeypatch, filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "averageVolume": 1_000})
    passed, reason = filt.filter("THIN")
    assert passed is False and "成交量" in reason


def test_rejects_high_pe(monkeypatch, filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": 90.0})
    passed, reason = filt.filter("RICH")
    assert passed is False and "市盈率" in reason


def test_rejects_loss_making_when_configured(monkeypatch):
    filt = FundamentalFilter({"enabled": True, "exclude_negative_eps": True})
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": None})
    passed, reason = filt.filter("LOSS")
    assert passed is False and "虧損" in reason


def test_allows_loss_making_when_permitted(monkeypatch):
    filt = FundamentalFilter({"enabled": True, "exclude_negative_eps": False})
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": None})
    passed, _ = filt.filter("LOSS")
    assert passed is True


def test_rejects_weak_earnings_growth(monkeypatch, filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "earningsGrowth": 0.01})
    passed, reason = filt.filter("SLOW")
    assert passed is False and "盈利增長" in reason


def test_network_error_fails_open(monkeypatch, filt):
    patch_ticker(monkeypatch, raise_error=True)
    passed, reason = filt.filter("ERR")
    assert passed is True and "跳過" in reason


# ----- caching (M15) -----

def test_cache_prevents_repeat_fetch(monkeypatch):
    filt = FundamentalFilter({"enabled": True, "cache_ttl_seconds": 3600})
    patch_ticker(monkeypatch, GOOD_INFO)
    filt.filter("AAPL")
    filt.filter("AAPL")
    filt.filter("AAPL")
    assert StubTicker.calls == 1


def test_cache_expires(monkeypatch):
    filt = FundamentalFilter({"enabled": True, "cache_ttl_seconds": 0})
    patch_ticker(monkeypatch, GOOD_INFO)
    filt.filter("AAPL")
    filt.filter("AAPL")
    assert StubTicker.calls == 2


def test_clear_cache_for_symbol(monkeypatch):
    filt = FundamentalFilter({"enabled": True})
    patch_ticker(monkeypatch, GOOD_INFO)
    filt.filter("AAPL")
    filt.clear_cache("AAPL")
    filt.filter("AAPL")
    assert StubTicker.calls == 2


def test_clear_entire_cache(monkeypatch):
    filt = FundamentalFilter({"enabled": True})
    patch_ticker(monkeypatch, GOOD_INFO)
    filt.filter("AAPL")
    filt.clear_cache()
    assert filt._cache == {}


def test_get_earnings_date(monkeypatch, filt):
    patch_ticker(monkeypatch, GOOD_INFO)
    assert filt.get_earnings_date("AAPL") == "2026-09-01"


# ----- retail mode: tier instead of veto -----

@pytest.fixture
def retail_filt():
    return FundamentalFilter({"enabled": True, "mode": "retail"})


def test_retail_mode_grades_quality_stock_as_tier_a(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, GOOD_INFO)
    view = retail_filt.assess("AAPL")
    assert view.passed is True
    assert view.tier == "A"


def test_retail_mode_allows_loss_making_growth_as_tier_c(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": None, "forwardPE": 25.0})
    view = retail_filt.assess("LOSS")
    assert view.passed is True
    assert view.tier == "C"


def test_retail_mode_allows_high_pe_growth(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": 45.0})
    view = retail_filt.assess("RICH")
    assert view.passed is True
    assert view.tier in ("A", "B")


def test_retail_mode_flags_extreme_pe_as_tier_c(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": 150.0})
    view = retail_filt.assess("BUBBLE")
    assert view.passed is True
    assert view.tier == "C"


def test_retail_mode_still_vetoes_micro_caps(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "marketCap": 20_000_000})
    view = retail_filt.assess("MICRO")
    assert view.passed is False
    assert view.tier == "D"


def test_retail_mode_still_vetoes_illiquid_names(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, {**GOOD_INFO, "averageVolume": 10_000})
    view = retail_filt.assess("THIN")
    assert view.passed is False
    assert view.tier == "D"


def test_retail_mode_can_forbid_unprofitable(monkeypatch):
    filt = FundamentalFilter(
        {"enabled": True, "mode": "retail", "retail": {"allow_unprofitable": False}}
    )
    patch_ticker(monkeypatch, {**GOOD_INFO, "trailingPE": None})
    assert filt.assess("LOSS").passed is False


def test_accuracy_flags_surface_data_gaps(monkeypatch, retail_filt):
    patch_ticker(
        monkeypatch,
        {**GOOD_INFO, "trailingPE": 90.0, "forwardPE": 20.0, "profitMargins": -0.2},
    )
    view = retail_filt.assess("FLAGS")
    joined = " ".join(view.flags)
    assert "forward PE" in joined
    assert "虧損中" in joined


def test_view_serialises_for_reports(monkeypatch, retail_filt):
    patch_ticker(monkeypatch, GOOD_INFO)
    payload = retail_filt.assess("AAPL").to_dict()
    assert payload["tier"] == "A"
    assert payload["metrics"]["market_cap"] == GOOD_INFO["marketCap"]
