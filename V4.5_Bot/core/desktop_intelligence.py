"""Market-wide intelligence feed with 1-10 scoring for V4.5 Desktop."""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import requests
import yfinance as yf

from core.news_providers import score_headline
from core.regime import RegimeDetector

logger = logging.getLogger(__name__)

MARKET_QUERIES = [
    "US stock market",
    "S&P 500",
    "Federal Reserve",
    "earnings report",
    "NASDAQ",
]


@dataclass
class IntelligenceItem:
    headline: str
    source: str
    url: str = ""
    published: datetime | None = None
    symbols: list[str] = field(default_factory=list)
    raw_sentiment: float = 0.0
    score: float = 5.0
    score_label: str = "中性"
    impact: int = 1
    category: str = "NEWS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "source": self.source,
            "url": self.url,
            "published": self.published.isoformat() if self.published else None,
            "symbols": self.symbols,
            "raw_sentiment": round(self.raw_sentiment, 3),
            "score": round(self.score, 1),
            "score_label": self.score_label,
            "impact": self.impact,
            "category": self.category,
        }


class DesktopIntelligence:
    """Aggregates US market news with sentiment-adjusted 1-10 scores."""

    POLL_SECONDS = 120
    KNOWN_TICKERS = {
        "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
        "SPY", "QQQ", "IWM", "DIA", "AMD", "INTC", "JPM", "BAC", "XOM",
        "CVX", "LLY", "UNH", "WMT", "COST", "NFLX", "CRM", "ORCL", "IBM",
        "GS", "MS", "V", "MA", "HD", "PG", "KO", "PEP", "MRK", "ABBV",
        "AVGO", "QCOM", "TXN", "MU", "SMCI", "PLTR", "COIN", "HOOD",
        "CRWD", "MSFT", "ULTA", "TGT", "ALLY", "BSX", "ABT", "USO", "SPY",
        "LMT", "RTX", "MRVL", "GOOGL",
    }

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.api_key = cfg.get("finnhub_key") or os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY") or ""
        self.regime = RegimeDetector(cfg.get("regime"))
        self._cache: list[IntelligenceItem] = []
        self._last_poll = 0.0
        self._market_mood = 5.0
        self._client = None
        if self.api_key:
            try:
                import finnhub

                self._client = finnhub.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Finnhub intelligence client failed: %s", exc)

    def _score_label(self, score: float) -> str:
        if score >= 9:
            return "強烈看漲"
        if score >= 7:
            return "溫和看漲"
        if score >= 5:
            return "中性"
        if score >= 3:
            return "溫和看跌"
        return "強烈看跌"

    def _sentiment_to_score(self, raw: float, mood_adj: float) -> float:
        """Map [-1,1] sentiment to [1,10] with market mood adjustment."""
        base = 5.0 + raw * 4.5
        adjusted = base + (mood_adj - 5.0) * 0.15
        return max(1.0, min(10.0, adjusted))

    def _impact_level(self, headline: str, score: float) -> int:
        strong = any(
            w in headline.lower()
            for w in ("surge", "crash", "record", "fed", "war", "default", "bankruptcy")
        )
        if strong or score <= 2 or score >= 9:
            return 5
        if score <= 3 or score >= 8:
            return 3
        return 1

    def _extract_symbols(self, text: str) -> list[str]:
        found: list[str] = []
        tokens = text.replace("$", " ").replace(",", " ").split()
        for tok in tokens:
            clean = tok.strip().upper()
            if len(clean) <= 5 and clean.isalpha() and clean in self.KNOWN_TICKERS:
                if clean not in found:
                    found.append(clean)
        return found[:6]

    def _update_market_mood(self) -> float:
        try:
            result = self.regime.detect()
            self._market_mood = max(1.0, min(10.0, result.score / 10.0))
        except Exception as exc:
            logger.debug("regime mood failed: %s", exc)
        return self._market_mood

    def _fetch_google_rss(self, query: str) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        q = quote_plus(f"{query} when:1d")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": "V45Desktop/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            logger.debug("google rss %s: %s", query, exc)
            return items

        mood = self._update_market_mood()
        for node in root.findall(".//item")[:15]:
            title = (node.findtext("title") or "").strip()
            if not title:
                continue
            link = node.findtext("link") or ""
            published = None
            pub = node.findtext("pubDate")
            if pub:
                try:
                    published = parsedate_to_datetime(pub).replace(tzinfo=None)
                except (TypeError, ValueError):
                    published = None
            raw = score_headline(title)
            score = self._sentiment_to_score(raw, mood)
            items.append(
                IntelligenceItem(
                    headline=title,
                    source="Google News",
                    url=link,
                    published=published,
                    symbols=self._extract_symbols(title),
                    raw_sentiment=raw,
                    score=score,
                    score_label=self._score_label(score),
                    impact=self._impact_level(title, score),
                )
            )
        return items

    def _fetch_finnhub_market(self) -> list[IntelligenceItem]:
        if not self._client:
            return []
        items: list[IntelligenceItem] = []
        mood = self._update_market_mood()
        try:
            raw = self._client.general_news("general", min_id=0)
        except Exception as exc:
            logger.debug("finnhub general news: %s", exc)
            return items
        for entry in (raw or [])[:30]:
            headline = (entry.get("headline") or "").strip()
            if not headline:
                continue
            published = None
            ts = entry.get("datetime")
            if ts:
                try:
                    published = datetime.fromtimestamp(int(ts))
                except (TypeError, ValueError, OSError):
                    published = None
            related = [str(s).upper() for s in (entry.get("related") or [])[:6]]
            raw_sent = score_headline(headline)
            score = self._sentiment_to_score(raw_sent, mood)
            items.append(
                IntelligenceItem(
                    headline=headline,
                    source=entry.get("source") or "Finnhub",
                    url=entry.get("url") or "",
                    published=published,
                    symbols=related or self._extract_symbols(headline),
                    raw_sentiment=raw_sent,
                    score=score,
                    score_label=self._score_label(score),
                    impact=self._impact_level(headline, score),
                    category=str(entry.get("category") or "NEWS"),
                )
            )
        return items

    def _fetch_yahoo_market(self) -> list[IntelligenceItem]:
        items: list[IntelligenceItem] = []
        mood = self._update_market_mood()
        try:
            raw = yf.Ticker("SPY").news or []
        except Exception as exc:
            logger.debug("yahoo market news: %s", exc)
            return items
        for entry in raw[:20]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            published = None
            ts = entry.get("providerPublishTime")
            if ts:
                try:
                    published = datetime.fromtimestamp(int(ts))
                except (TypeError, ValueError, OSError):
                    published = None
            raw_sent = score_headline(title)
            score = self._sentiment_to_score(raw_sent, mood)
            items.append(
                IntelligenceItem(
                    headline=title,
                    source="Yahoo Finance",
                    url=entry.get("link") or "",
                    published=published,
                    symbols=self._extract_symbols(title),
                    raw_sentiment=raw_sent,
                    score=score,
                    score_label=self._score_label(score),
                    impact=self._impact_level(title, score),
                )
            )
        return items

    def _dedupe(self, items: list[IntelligenceItem]) -> list[IntelligenceItem]:
        seen: set[str] = set()
        unique: list[IntelligenceItem] = []
        for item in items:
            key = "".join(ch for ch in item.headline.lower() if ch.isalnum())[:80]
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda x: x.published or datetime.min, reverse=True)
        return unique

    def poll(self, force: bool = False) -> list[IntelligenceItem]:
        now = time.time()
        if not force and self._cache and (now - self._last_poll) < self.POLL_SECONDS:
            return self._cache

        all_items: list[IntelligenceItem] = []
        all_items.extend(self._fetch_finnhub_market())
        all_items.extend(self._fetch_yahoo_market())
        for q in MARKET_QUERIES[:3]:
            all_items.extend(self._fetch_google_rss(q))

        self._cache = self._dedupe(all_items)
        self._last_poll = now
        return self._cache

    def get_feed(self, limit: int = 50, min_score: float | None = None) -> list[dict[str, Any]]:
        items = self.poll()
        if min_score is not None:
            items = [i for i in items if i.score >= min_score or i.score <= (10 - min_score)]
        return [i.to_dict() for i in items[:limit]]

    def get_headlines(self, limit: int = 20) -> list[dict[str, Any]]:
        """Only extreme scores: 1-2 or 9-10."""
        items = self.poll()
        extreme = [i for i in items if i.score <= 2 or i.score >= 9]
        return [i.to_dict() for i in extreme[:limit]]

    def get_hot_trends(self, limit: int = 20) -> list[dict[str, Any]]:
        items = self.poll()
        scored = sorted(items, key=lambda x: (x.impact, abs(x.score - 5)), reverse=True)
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(scored[:limit], 1):
            d = item.to_dict()
            d["rank"] = idx
            d["article_count"] = max(1, item.impact)
            out.append(d)
        return out

    def get_symbol_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        sym = symbol.upper()
        items: list[IntelligenceItem] = []
        mood = self._update_market_mood()
        try:
            raw = yf.Ticker(sym).news or []
            for entry in raw[:limit]:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                raw_sent = score_headline(title)
                score = self._sentiment_to_score(raw_sent, mood)
                published = None
                ts = entry.get("providerPublishTime")
                if ts:
                    try:
                        published = datetime.fromtimestamp(int(ts))
                    except (TypeError, ValueError, OSError):
                        published = None
                items.append(
                    IntelligenceItem(
                        headline=title,
                        source="Yahoo Finance",
                        url=entry.get("link") or "",
                        published=published,
                        symbols=[sym],
                        raw_sentiment=raw_sent,
                        score=score,
                        score_label=self._score_label(score),
                        impact=self._impact_level(title, score),
                    )
                )
        except Exception as exc:
            logger.debug("symbol news %s: %s", sym, exc)
        return [i.to_dict() for i in items]
