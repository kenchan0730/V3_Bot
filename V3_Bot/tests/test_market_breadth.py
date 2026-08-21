import io

import pytest

from core.market_breadth import MarketBreadth

CSV_BODY = (
    "date,composite_score,health_zone,breadth_level_trend,ma_crossover,peak_trough,"
    "bearish_signal,historical_percentile,sp500_divergence\n"
    "2026-08-20,72.5,HEALTHY,10,5,3,-2,60,1\n"
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def patch_urlopen(monkeypatch, body=None, error=None):
    def fake_urlopen(request, timeout=None):
        if error:
            raise error
        return FakeResponse(body.encode("utf-8"))

    monkeypatch.setattr("core.market_breadth.urllib.request.urlopen", fake_urlopen)


def test_fetch_csv_success(monkeypatch):
    patch_urlopen(monkeypatch, CSV_BODY)
    assert "composite_score" in MarketBreadth.fetch_csv("http://example.com/x.csv")


def test_fetch_csv_failure_returns_none(monkeypatch):
    patch_urlopen(monkeypatch, error=OSError("unreachable"))
    assert MarketBreadth.fetch_csv("http://example.com/x.csv") is None


def test_get_breadth_score_parses_csv(monkeypatch):
    patch_urlopen(monkeypatch, CSV_BODY)
    result = MarketBreadth.get_breadth_score()
    assert result["score"] == 72.5
    assert result["zone"] == "HEALTHY"
    assert result["date"] == "2026-08-20"
    assert result["components"]["ma_crossover"] == 5.0


def test_get_breadth_score_falls_back_on_failure(monkeypatch):
    patch_urlopen(monkeypatch, error=OSError("no network"))
    result = MarketBreadth.get_breadth_score()
    assert result["score"] == 50
    assert result["zone"] == "NEUTRAL"


def test_get_breadth_score_handles_empty_csv(monkeypatch):
    patch_urlopen(monkeypatch, "date,composite_score\n")
    result = MarketBreadth.get_breadth_score()
    assert result["score"] == 50


@pytest.mark.parametrize("score,zone", [
    (95, "STRONG"),
    (70, "HEALTHY"),
    (50, "NEUTRAL"),
    (30, "WEAKENING"),
    (10, "CRITICAL"),
])
def test_health_zones(score, zone):
    assert MarketBreadth.get_health_zone(score)[0] == zone


@pytest.mark.parametrize("score,exposure", [
    (95, 100),
    (70, 75),
    (50, 50),
    (30, 25),
    (10, 0),
])
def test_exposure_recommendations(score, exposure):
    assert MarketBreadth.get_exposure_recommendation(score) == exposure


def test_health_zone_returns_message():
    _, message = MarketBreadth.get_health_zone(85)
    assert message
