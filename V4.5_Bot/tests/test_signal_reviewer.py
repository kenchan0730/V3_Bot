import pandas as pd

from core.external_signals import ExternalSignal
from core.news_credibility import NewsCredibilityAuditor
from core.news_providers import NewsItem
from core.retail_mind import RetailMind
from core.signal_reviewer import ExternalSignalReviewer, SymbolAnalysis
from core.strategies.base import MarketContext


def make_df(rows=80, close=20.0):
    return pd.DataFrame(
        {
            "open": [close] * rows,
            "high": [close * 1.01] * rows,
            "low": [close * 0.99] * rows,
            "close": [close] * rows,
            "volume": [1_500_000] * rows,
        }
    )


def good_analysis(symbol="AVAH", quality_ok=True):
    context = MarketContext(
        symbol=symbol, price=20.0, quant={"rsi": 55, "z_score": 0.9},
        vol_ratio=1.3, ma20=19.5, ma50=18.0,
    )
    return SymbolAnalysis(
        symbol=symbol, ok=True, stage="SIGNAL", price=20.0, df=make_df(),
        quant={"rsi": 55}, context=context,
        signal={
            "action": "STRONG_BUY", "track": "STRONG", "entry": 20.0,
            "stop": 19.0, "target1": 22.0, "confluence_score": 7,
        },
        fundamental_view={"tier": "B", "passed": True},
        news_view={"score": 0.3, "total": 5},
        quality_ok=quality_ok,
        quality_reason="品質 OK" if quality_ok else "RSI 過高",
    )


class StubProvider:
    name = "stub"
    weight = 1.0

    def __init__(self, items):
        self.items = items

    def fetch(self, symbol, days):
        return self.items


class StubNews:
    days = 3

    def __init__(self, items):
        self.providers = [StubProvider(items)]


def build_reviewer(analysis, news_items=None, capital=5000.0):
    return ExternalSignalReviewer(
        analyzer=lambda symbol: analysis,
        credibility=NewsCredibilityAuditor(),
        retail_mind=RetailMind(),
        news=StubNews(news_items or []),
        fundamental=None,
        capital_fn=lambda: capital,
        max_shares=50,
        max_symbol_pct=100.0,
    )


def signal(note="", symbol="AVAH"):
    return ExternalSignal.from_dict({"symbol": symbol, "note": note})


def test_verified_story_with_clean_setup_is_a_buy():
    items = [
        NewsItem("Avah wins federal home health contract", "yahoo", "https://www.reuters.com/a"),
        NewsItem("Avah federal home health contract expansion", "google_rss", "https://www.cnbc.com/b"),
    ]
    reviewer = build_reviewer(good_analysis(), news_items=items)
    report = reviewer.review(signal("Avah wins federal home health contract expansion"))
    assert report["credibility"]["verdict"] == "VERIFIED"
    assert report["verdict"] == "BUY"


def test_unverified_story_downgrades_to_watch():
    reviewer = build_reviewer(good_analysis(), news_items=[])
    report = reviewer.review(signal("Avah secures a secret mega contract"))
    assert report["credibility"]["verdict"] == "UNVERIFIED"
    assert report["verdict"] == "WATCH"


def test_contradicted_story_is_skipped():
    items = [
        NewsItem("Avah faces fraud probe over billing", "yahoo", "https://www.reuters.com/a"),
        NewsItem("Avah lawsuit over billing practices", "google_rss", "https://www.wsj.com/b"),
    ]
    reviewer = build_reviewer(good_analysis(), news_items=items)
    report = reviewer.review(signal("Avah billing fraud probe lawsuit"))
    assert report["credibility"]["verdict"] == "CONTRADICTED"
    assert report["verdict"] == "SKIP"


def test_no_claim_still_reviews_technicals():
    reviewer = build_reviewer(good_analysis())
    report = reviewer.review(signal(""))
    assert report["credibility"]["verdict"] == "NO_CLAIM"
    assert report["verdict"] == "BUY"
    assert report["retail"]["score"] > 0


def test_failed_quality_gate_is_not_a_buy():
    reviewer = build_reviewer(good_analysis(quality_ok=False))
    report = reviewer.review(signal(""))
    assert report["verdict"] != "BUY"
    assert "品質過濾" in report["explanation"]


def test_data_stage_failure_short_circuits():
    analysis = SymbolAnalysis(symbol="AVAH", ok=False, stage="DATA", reason="數據不可用")
    reviewer = build_reviewer(analysis)
    report = reviewer.review(signal("something"))
    assert report["verdict"] == "SKIP"
    assert "DATA" in report["explanation"]


def test_unaffordable_idea_is_rejected_even_with_verified_news():
    items = [
        NewsItem("Avah wins federal home health contract", "yahoo", "https://www.reuters.com/a"),
        NewsItem("Avah federal home health contract expansion", "google_rss", "https://www.cnbc.com/b"),
    ]
    reviewer = build_reviewer(good_analysis(), news_items=items, capital=30.0)
    report = reviewer.review(signal("Avah wins federal home health contract expansion"))
    assert report["verdict"] == "SKIP"
    assert report["retail"]["verdict"] == "SKIP"
