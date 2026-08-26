import pytest

from core.news_providers import BaseNewsProvider, dedupe_headlines, score_headline, NewsItem
from core.news_sentiment import NewsSentiment
from core.market_data_sources import assess_quote_freshness
from core.realtime_pulse import RealtimePulse


class StubProvider(BaseNewsProvider):
    name = "stub"

    def __init__(self, headlines=None, raise_error=False):
        super().__init__()
        self.headlines = headlines or []
        self.raise_error = raise_error

    def fetch(self, symbol, days):
        if self.raise_error:
            raise RuntimeError("provider down")
        return [
            NewsItem(headline=h, provider=self.name, sentiment_score=score_headline(h))
            for h in self.headlines
        ]


def build(headlines=None, raise_error=False, enabled=True):
    sentiment = NewsSentiment({"enabled": enabled, "sources": [{"name": "yahoo", "enabled": True}]})
    sentiment.providers = [StubProvider(headlines, raise_error)]
    sentiment.client = None
    return sentiment


def test_disabled_returns_neutral():
    result = NewsSentiment({"enabled": False}).get_sentiment("AVAH")
    assert result["sentiment"] == "neutral"
    assert result["score"] == 0


def test_no_providers_returns_neutral():
    sentiment = NewsSentiment({"enabled": True, "sources": []})
    assert sentiment.get_sentiment("AVAH")["sentiment"] == "neutral"


def test_positive_headlines_score_positive():
    result = build(["Company beats estimates with record growth",
                    "Analyst upgrade drives strong gain"]).get_sentiment("AVAH")
    assert result["sentiment"] == "positive"
    assert result["score"] > 0


def test_negative_headlines_score_negative():
    result = build(["Revenue miss triggers downgrade",
                    "Shares fall on weak guidance and loss"]).get_sentiment("AVAH")
    assert result["sentiment"] == "negative"
    assert result["score"] < 0


def test_neutral_headlines():
    result = build(["Company announces annual meeting date"]).get_sentiment("AVAH")
    assert result["sentiment"] == "neutral"


def test_no_news_returns_neutral():
    result = build([]).get_sentiment("AVAH")
    assert result["total"] == 0


def test_api_error_returns_neutral_when_fail_open():
    result = build(raise_error=True).get_sentiment("AVAH")
    assert result["sentiment"] == "neutral"


def test_api_error_blocks_when_fail_closed():
    sentiment = NewsSentiment({"enabled": True, "fail_mode": "closed", "sources": []})
    sentiment.providers = [StubProvider(raise_error=True)]
    result = sentiment.get_sentiment("AVAH")
    assert result["sentiment"] == "unknown"


def test_analyses_at_most_twenty_headlines():
    headlines = [f"strong beat number {i}" for i in range(40)]
    result = build(headlines).get_sentiment("AVAH")
    assert result["total"] == 20


def test_details_are_truncated_to_five():
    headlines = [f"record high growth {i}" for i in range(10)]
    result = build(headlines).get_sentiment("AVAH")
    assert len(result["details"]) == 5


def test_long_headline_is_shortened():
    long_headline = "beat " * 40
    result = build([long_headline]).get_sentiment("AVAH")
    assert result["details"][0]["headline"].endswith("...")


def test_analyze_headline_is_bounded():
    sentiment = build([])
    assert sentiment._analyze_headline("beat surpass growth upgrade buy strong record high rise gain") == 1
    assert sentiment._analyze_headline("miss downgrade sell weak low fall drop loss decline cut") == -1


def test_is_sentiment_ok_blocks_negative():
    ok, message = build(["miss weak loss decline drop"]).is_sentiment_ok("AVAH")
    assert ok is False and "負面" in message


def test_is_sentiment_ok_allows_positive():
    ok, message = build(["record beat growth"]).is_sentiment_ok("AVAH")
    assert ok is True and "positive" in message


def test_is_sentiment_ok_when_disabled():
    ok, _ = NewsSentiment({"enabled": False}).is_sentiment_ok("AVAH")
    assert ok is True


def test_dedupe_headlines():
    items = [
        NewsItem(headline="Apple beats earnings", provider="yahoo"),
        NewsItem(headline="Apple beats earnings!", provider="google_rss"),
        NewsItem(headline="Different headline", provider="finnhub"),
    ]
    unique = dedupe_headlines(items)
    assert len(unique) == 2


def test_assess_quote_freshness_stale():
    quote = {"price": 10.0, "age_seconds": 1200, "source": "yfinance"}
    result = assess_quote_freshness(quote, max_age_seconds=900)
    assert result["stale"] is True


def test_realtime_pulse_blocks_stale_when_configured(monkeypatch):
    pulse = RealtimePulse({"enabled": True, "block_stale_quote": True, "max_quote_age_seconds": 60})
    monkeypatch.setattr(
        "core.realtime_pulse.fetch_realtime_quote",
        lambda *a, **k: {"price": 12.0, "timestamp": None, "age_seconds": 120, "source": "yfinance"},
    )
    monkeypatch.setattr(
        "core.realtime_pulse.assess_quote_freshness",
        lambda q, m: {"fresh": False, "stale": True, "reason": "old", "source": "yfinance"},
    )
    result = pulse.check("AAPL", last_close=11.0)
    assert result["ok"] is False
