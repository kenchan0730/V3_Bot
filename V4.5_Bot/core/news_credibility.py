"""Institutional-grade credibility audit for a news claim.

A retail app push ("XYZ wins a huge contract") is a hypothesis, not a fact.
Before that claim is allowed to influence sizing it is checked the way a desk
would check it: does a reputable outlet carry it, do independent outlets carry
it, and is it recent enough to still be tradable?

No paid vendor is required — corroboration is measured across the free news
providers already wired into ``NewsSentiment``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Rough newsroom quality tiers. Primary wires first, aggregators and
# opinion-driven outlets last.
SOURCE_TIERS = {
    "reuters.com": 1.0,
    "bloomberg.com": 1.0,
    "apnews.com": 1.0,
    "wsj.com": 0.95,
    "ft.com": 0.95,
    "sec.gov": 1.0,
    "prnewswire.com": 0.8,
    "businesswire.com": 0.8,
    "globenewswire.com": 0.8,
    "cnbc.com": 0.85,
    "barrons.com": 0.85,
    "marketwatch.com": 0.8,
    "forbes.com": 0.7,
    "finance.yahoo.com": 0.7,
    "yahoo.com": 0.7,
    "investors.com": 0.7,
    "benzinga.com": 0.6,
    "seekingalpha.com": 0.6,
    "thestreet.com": 0.6,
    "zacks.com": 0.55,
    "fool.com": 0.5,
    "investorplace.com": 0.45,
    "simplywall.st": 0.45,
}
DEFAULT_TIER = 0.5

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "is", "are", "was", "were", "be", "been", "as",
    "its", "it", "that", "this", "will", "has", "have", "after", "over",
    "into", "amid", "says", "said", "new", "stock", "shares", "inc", "corp",
}

STRONG_NEGATIVE = (
    "fraud", "lawsuit", "probe", "investigation", "subpoena", "delist",
    "bankruptcy", "restatement", "short report", "halted",
)


@dataclass
class CredibilityReport:
    verdict: str = "UNVERIFIED"    # VERIFIED | PARTIAL | UNVERIFIED | CONTRADICTED
    confidence: float = 0.0
    matched_headlines: list = field(default_factory=list)
    independent_domains: list = field(default_factory=list)
    providers: list = field(default_factory=list)
    best_source_tier: float = 0.0
    age_hours: float | None = None
    reasons: list = field(default_factory=list)

    @property
    def trustworthy(self) -> bool:
        return self.verdict in ("VERIFIED", "PARTIAL")

    def summary(self) -> str:
        return (
            f"{self.verdict} (可信度 {self.confidence:.0%}, "
            f"{len(self.independent_domains)} 個獨立來源)"
        )

    def to_dict(self):
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "matched_headlines": self.matched_headlines[:5],
            "independent_domains": self.independent_domains,
            "providers": self.providers,
            "best_source_tier": self.best_source_tier,
            "age_hours": round(self.age_hours, 1) if self.age_hours is not None else None,
            "reasons": self.reasons,
        }


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def source_tier(url: str) -> float:
    domain = domain_of(url)
    if not domain:
        return DEFAULT_TIER
    for known, tier in SOURCE_TIERS.items():
        if domain == known or domain.endswith("." + known):
            return tier
    return DEFAULT_TIER


class NewsCredibilityAuditor:
    """Cross-check a claim against headlines already fetched from providers."""

    DEFAULTS = {
        "enabled": True,
        "min_token_overlap": 0.28,
        "min_domains_for_verified": 2,
        "min_confidence_for_verified": 0.65,
        "min_confidence_for_partial": 0.40,
        "max_age_hours": 72,
        "trusted_tier_floor": 0.8,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def audit(self, claim: str, items, now=None) -> CredibilityReport:
        report = CredibilityReport()
        if not self.cfg.get("enabled", True):
            report.verdict = "PARTIAL"
            report.confidence = 0.5
            report.reasons = ["credibility audit disabled"]
            return report

        claim_tokens = tokenize(claim)
        if not claim_tokens:
            report.reasons = ["消息內容過短，無法比對"]
            return report

        now = now or datetime.now()
        min_overlap = float(self.cfg["min_token_overlap"])
        matches = []
        domains: dict[str, float] = {}
        providers: set[str] = set()
        newest: datetime | None = None
        negative_hits = 0

        for item in items or []:
            headline = getattr(item, "headline", None) or (
                item.get("headline") if isinstance(item, dict) else None
            )
            if not headline:
                continue
            url = getattr(item, "url", None) or (
                item.get("url", "") if isinstance(item, dict) else ""
            )
            provider = getattr(item, "provider", None) or (
                item.get("provider", "") if isinstance(item, dict) else ""
            )
            published = getattr(item, "published", None) or (
                item.get("published") if isinstance(item, dict) else None
            )

            tokens = tokenize(headline)
            if not tokens:
                continue
            overlap = len(claim_tokens & tokens) / len(claim_tokens)
            if overlap < min_overlap:
                continue

            tier = source_tier(url)
            domain = domain_of(url) or f"provider:{provider}"
            domains[domain] = max(domains.get(domain, 0.0), tier)
            if provider:
                providers.add(provider)
            matches.append(
                {
                    "headline": headline[:120],
                    "overlap": round(overlap, 2),
                    "domain": domain,
                    "tier": tier,
                }
            )
            if isinstance(published, datetime) and (newest is None or published > newest):
                newest = published
            lowered = headline.lower()
            if any(word in lowered for word in STRONG_NEGATIVE):
                negative_hits += 1

        report.matched_headlines = matches
        report.independent_domains = sorted(domains)
        report.providers = sorted(providers)
        report.best_source_tier = round(max(domains.values()), 2) if domains else 0.0

        if newest:
            report.age_hours = max(0.0, (now - newest).total_seconds() / 3600.0)

        if not matches:
            report.verdict = "UNVERIFIED"
            report.confidence = 0.0
            report.reasons = ["找不到任何來源報導此消息 — 視為未經證實"]
            return report

        domain_count = len(domains)
        corroboration = min(1.0, domain_count / max(1, int(self.cfg["min_domains_for_verified"])))
        confidence = report.best_source_tier * 0.55 + corroboration * 0.45

        if report.age_hours is not None:
            max_age = float(self.cfg["max_age_hours"])
            if report.age_hours > max_age:
                confidence *= 0.6
                report.reasons.append(
                    f"消息已 {report.age_hours:.0f} 小時（超過 {max_age:.0f}h），時效性下降"
                )

        if negative_hits:
            report.reasons.append(f"{negative_hits} 則相關報導含法律／調查風險字眼")

        report.confidence = round(min(1.0, confidence), 3)

        if negative_hits and negative_hits >= max(1, len(matches) // 2):
            report.verdict = "CONTRADICTED"
            report.reasons.insert(0, "多數相關報導為負面事件，與買入論點相反")
            return report

        if (
            domain_count >= int(self.cfg["min_domains_for_verified"])
            and report.confidence >= float(self.cfg["min_confidence_for_verified"])
        ):
            report.verdict = "VERIFIED"
            report.reasons.insert(
                0, f"{domain_count} 個獨立來源證實（最佳來源評級 {report.best_source_tier}）"
            )
        elif report.confidence >= float(self.cfg["min_confidence_for_partial"]):
            report.verdict = "PARTIAL"
            report.reasons.insert(
                0, f"僅 {domain_count} 個來源報導，證據不足以完全確認"
            )
        else:
            report.verdict = "UNVERIFIED"
            report.reasons.insert(0, "來源品質偏低，無法確認")
        return report
