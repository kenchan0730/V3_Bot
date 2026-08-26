from datetime import datetime, timedelta

from core.news_credibility import NewsCredibilityAuditor, source_tier
from core.news_providers import NewsItem


CLAIM = "Avah wins large federal home health contract expansion"


def item(headline, url, provider="yahoo", hours_ago=2):
    return NewsItem(
        headline=headline,
        provider=provider,
        url=url,
        published=datetime.now() - timedelta(hours=hours_ago),
    )


def test_source_tier_recognises_wires_and_blogs():
    assert source_tier("https://www.reuters.com/x") > source_tier("https://investorplace.com/y")
    assert source_tier("") == 0.5


def test_no_matching_coverage_is_unverified():
    report = NewsCredibilityAuditor().audit(
        CLAIM, [item("Unrelated market wrap for Tuesday", "https://cnbc.com/a")]
    )
    assert report.verdict == "UNVERIFIED"
    assert report.trustworthy is False


def test_two_independent_reputable_domains_verify():
    items = [
        item("Avah wins large federal home health contract", "https://www.reuters.com/a"),
        item("Avah lands federal home health contract expansion", "https://www.cnbc.com/b",
             provider="google_rss"),
    ]
    report = NewsCredibilityAuditor().audit(CLAIM, items)
    assert report.verdict == "VERIFIED"
    assert len(report.independent_domains) == 2
    assert report.confidence >= 0.65


def test_single_low_tier_source_is_partial_at_best():
    items = [item("Avah wins federal home health contract expansion",
                  "https://investorplace.com/a")]
    report = NewsCredibilityAuditor().audit(CLAIM, items)
    assert report.verdict in ("PARTIAL", "UNVERIFIED")
    assert len(report.independent_domains) == 1


def test_negative_coverage_contradicts_a_bullish_claim():
    items = [
        item("Avah faces fraud probe over home health billing", "https://www.reuters.com/a"),
        item("Avah lawsuit filed over federal contract claims", "https://www.wsj.com/b"),
    ]
    report = NewsCredibilityAuditor().audit(
        "Avah federal home health contract lawsuit probe", items
    )
    assert report.verdict == "CONTRADICTED"


def test_stale_news_reduces_confidence():
    fresh = NewsCredibilityAuditor().audit(
        CLAIM,
        [
            item("Avah wins large federal home health contract", "https://www.reuters.com/a", hours_ago=1),
            item("Avah federal home health contract expansion", "https://www.cnbc.com/b", hours_ago=1),
        ],
    )
    stale = NewsCredibilityAuditor().audit(
        CLAIM,
        [
            item("Avah wins large federal home health contract", "https://www.reuters.com/a", hours_ago=400),
            item("Avah federal home health contract expansion", "https://www.cnbc.com/b", hours_ago=400),
        ],
    )
    assert stale.confidence < fresh.confidence


def test_empty_claim_is_not_auditable():
    report = NewsCredibilityAuditor().audit("", [item("anything", "https://x.com/a")])
    assert report.verdict == "UNVERIFIED"
    assert "過短" in report.reasons[0]


def test_dict_items_are_accepted():
    report = NewsCredibilityAuditor().audit(
        CLAIM,
        [
            {"headline": "Avah wins large federal home health contract",
             "url": "https://www.reuters.com/a", "provider": "custom"},
            {"headline": "Avah federal home health contract expansion",
             "url": "https://www.bloomberg.com/b", "provider": "custom"},
        ],
    )
    assert report.verdict == "VERIFIED"


def test_disabled_auditor_does_not_block():
    report = NewsCredibilityAuditor({"enabled": False}).audit(CLAIM, [])
    assert report.trustworthy is True
