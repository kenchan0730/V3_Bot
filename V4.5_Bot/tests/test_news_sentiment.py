import pytest

from core.news_sentiment import NewsSentiment


class StubClient:
    def __init__(self, headlines=None, raise_error=False):
        self.headlines = headlines or []
        self.raise_error = raise_error

    def company_news(self, symbol, _from=None, to=None):
        if self.raise_error:
            raise RuntimeError("finnhub down")
        return [{"headline": h} for h in self.headlines]


def build(headlines=None, raise_error=False, enabled=True):
    sentiment = NewsSentiment({"enabled": enabled, "finnhub_key": "key" if enabled else ""})
    sentiment.client = StubClient(headlines, raise_error) if enabled else None
    return sentiment


def test_disabled_returns_neutral():
    result = NewsSentiment({"enabled": False}).get_sentiment("AVAH")
    assert result["sentiment"] == "neutral"
    assert result["score"] == 0


def test_no_client_returns_neutral():
    sentiment = NewsSentiment({"enabled": True, "finnhub_key": ""})
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


def test_api_error_returns_neutral():
    result = build(raise_error=True).get_sentiment("AVAH")
    assert result["sentiment"] == "neutral"


def test_analyses_at_most_twenty_headlines():
    result = build(["strong beat"] * 40).get_sentiment("AVAH")
    assert result["total"] == 20


def test_details_are_truncated_to_five():
    result = build(["record high growth"] * 10).get_sentiment("AVAH")
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
    assert ok is False and "负面" in message


def test_is_sentiment_ok_allows_positive():
    ok, message = build(["record beat growth"]).is_sentiment_ok("AVAH")
    assert ok is True and "positive" in message


def test_is_sentiment_ok_when_disabled():
    ok, _ = NewsSentiment({"enabled": False}).is_sentiment_ok("AVAH")
    assert ok is True
